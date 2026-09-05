from datetime import datetime, time, timedelta

from django.test import TestCase
from django.utils import timezone

from chores import services
from chores.models import Chore, Member, PointsAward, Status


def finish(chore, actor, pauses=0):
    services.transition(chore, "start", actor=actor)
    for _ in range(pauses):
        services.transition(chore, "pause", actor=actor)
        services.transition(chore, "resume", actor=actor)
    services.transition(chore, "finish", actor=actor)
    return chore


class AwardTests(TestCase):
    def setUp(self):
        self.alex = Member.objects.create(name="Alex")
        self.sam = Member.objects.create(name="Sam")

    def _chore(self, points=5, owner=None):
        return Chore.objects.create(
            name="Clean the windows", points=points, assigned_to=owner
        )

    def test_clean_run_awards_full_points(self):
        chore = finish(self._chore(5, self.alex), self.alex)
        self.assertEqual(chore.points_awarded, 5)

    def test_each_pause_costs_one_point(self):
        chore = finish(self._chore(5, self.alex), self.alex, pauses=2)
        self.assertEqual(chore.points_awarded, 3)

    def test_penalty_floors_at_one_point(self):
        chore = finish(self._chore(2, self.alex), self.alex, pauses=9)
        self.assertEqual(chore.points_awarded, 1)

    def test_unassigned_chore_awards_zero(self):
        chore = finish(self._chore(4, None), self.alex)
        self.assertEqual(chore.points_awarded, 0)

    def test_unassigned_chore_still_records_completed_by(self):
        chore = finish(self._chore(4, None), self.alex)
        self.assertEqual(chore.completed_by, self.alex)
        self.assertEqual(chore.status, Status.COMPLETED)

    def test_completed_by_is_the_finisher_not_the_owner(self):
        chore = finish(self._chore(3, self.alex), self.sam)
        self.assertEqual(chore.assigned_to, self.alex)
        self.assertEqual(chore.completed_by, self.sam)
        self.assertEqual(services.member_points(self.sam), 3)
        self.assertEqual(services.member_points(self.alex), 0)

    def test_editing_points_later_does_not_change_past_awards(self):
        chore = finish(self._chore(5, self.alex), self.alex)
        chore.points = 1
        chore.save()
        self.assertEqual(services.member_points(self.alex), 5)


class StreakTests(TestCase):
    def setUp(self):
        self.alex = Member.objects.create(name="Alex")

    def _completed_on(self, day):
        chore = Chore.objects.create(
            name="Feed the pet", points=1, assigned_to=self.alex
        )
        finish(chore, self.alex)
        # Midday local, so the stamp cannot drift across a date boundary.
        stamp = timezone.make_aware(datetime.combine(day, time(12, 0)))
        Chore.objects.filter(pk=chore.pk).update(completed_at=stamp)
        PointsAward.objects.filter(chore=chore).update(awarded_at=stamp)
        return chore

    def test_streak_counts_consecutive_days(self):
        today = timezone.localdate()
        for offset in range(3):
            self._completed_on(today - timedelta(days=offset))
        self.assertEqual(services.streak(self.alex), 3)

    def test_streak_breaks_on_a_missed_day(self):
        today = timezone.localdate()
        self._completed_on(today)
        self._completed_on(today - timedelta(days=2))
        self.assertEqual(services.streak(self.alex), 1)

    def test_two_chores_same_day_count_as_one_streak_day(self):
        today = timezone.localdate()
        self._completed_on(today)
        self._completed_on(today)
        self.assertEqual(services.streak(self.alex), 1)

    def test_no_completions_is_zero_streak(self):
        self.assertEqual(services.streak(self.alex), 0)


class LeaderboardTests(TestCase):
    def test_leaderboard_orders_by_points(self):
        alex = Member.objects.create(name="Alex")
        sam = Member.objects.create(name="Sam")
        finish(
            Chore.objects.create(name="Mow the lawn", points=5, assigned_to=sam), sam
        )
        finish(
            Chore.objects.create(name="Make the bed", points=1, assigned_to=alex), alex
        )
        rows = services.leaderboard()
        self.assertEqual([r["member"] for r in rows], [sam, alex])
        self.assertEqual(rows[0]["points"], 5)

    def test_zero_point_completions_do_not_inflate_totals(self):
        alex = Member.objects.create(name="Alex")
        finish(Chore.objects.create(name="Dust surfaces", points=3), alex)
        self.assertEqual(services.member_points(alex), 0)

    def test_clean_run_rate_counts_unpaused_completions(self):
        alex = Member.objects.create(name="Alex")
        finish(
            Chore.objects.create(name="Make the bed", points=1, assigned_to=alex), alex
        )
        finish(
            Chore.objects.create(name="Iron a batch", points=3, assigned_to=alex),
            alex,
            pauses=1,
        )
        self.assertEqual(services.clean_run_rate(alex), 50)
