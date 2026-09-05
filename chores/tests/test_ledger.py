"""Points survive the chore, and a burned chore can be reclaimed at half rate."""

from django.test import TestCase
from django.utils import timezone
from django.urls import reverse

from chores import services
from chores.models import AwardReason, Chore, Member, PointsAward, Status
from chores.views import ACTOR_SESSION_KEY


def finish(chore, actor, pauses=0):
    services.transition(chore, "start", actor=actor)
    for _ in range(pauses):
        services.transition(chore, "pause", actor=actor)
        services.transition(chore, "resume", actor=actor)
    services.transition(chore, "finish", actor=actor)
    return chore


class LedgerSurvivalTests(TestCase):
    def setUp(self):
        self.alex = Member.objects.create(name="Alex")

    def test_completion_writes_one_ledger_row(self):
        chore = finish(
            Chore.objects.create(name="Mow the lawn", points=5, assigned_to=self.alex),
            self.alex,
        )
        award = PointsAward.objects.get()
        self.assertEqual(award.member, self.alex)
        self.assertEqual(award.points, 5)
        self.assertEqual(award.pauses, 0)
        self.assertEqual(award.reason, AwardReason.COMPLETED)
        self.assertEqual(award.chore, chore)

    def test_deleting_the_chore_keeps_the_points(self):
        chore = finish(
            Chore.objects.create(name="Mow the lawn", points=5, assigned_to=self.alex),
            self.alex,
        )
        chore.delete()

        self.assertEqual(services.member_points(self.alex), 5)
        award = PointsAward.objects.get()
        self.assertIsNone(award.chore)
        self.assertEqual(award.chore_name, "Mow the lawn")

    def test_deleting_the_chore_keeps_the_streak(self):
        chore = finish(
            Chore.objects.create(name="Feed the pet", points=1, assigned_to=self.alex),
            self.alex,
        )
        self.assertEqual(services.streak(self.alex), 1)
        chore.delete()
        self.assertEqual(services.streak(self.alex), 1)

    def test_deleting_an_unstarted_chore_leaves_no_trace(self):
        chore = Chore.objects.create(name="Iron a batch", points=3, assigned_to=self.alex)
        chore.delete()
        self.assertEqual(Chore.objects.count(), 0)
        self.assertEqual(PointsAward.objects.count(), 0)
        self.assertEqual(services.member_points(self.alex), 0)

    def test_deleting_a_paused_chore_pays_nothing(self):
        chore = Chore.objects.create(name="Iron a batch", points=3, assigned_to=self.alex)
        services.transition(chore, "start", actor=self.alex)
        services.transition(chore, "pause", actor=self.alex)
        chore.delete()
        self.assertEqual(PointsAward.objects.count(), 0, "unfinished work never paid")
        self.assertEqual(services.member_points(self.alex), 0)

    def test_deleting_a_member_removes_their_ledger(self):
        finish(
            Chore.objects.create(name="Mow the lawn", points=5, assigned_to=self.alex),
            self.alex,
        )
        self.alex.delete()
        self.assertEqual(PointsAward.objects.count(), 0)

    def test_burned_completion_is_ledgered_at_zero(self):
        finish(Chore.objects.create(name="Feed the pet", points=1), self.alex)
        award = PointsAward.objects.get()
        self.assertEqual(award.points, 0)
        self.assertEqual(services.member_points(self.alex), 0)


class ReclaimTests(TestCase):
    def setUp(self):
        self.alex = Member.objects.create(name="Alex")
        self.sam = Member.objects.create(name="Sam")

    def _burned(self, name="Mow the lawn", points=5, pauses=0, doer=None):
        return finish(
            Chore.objects.create(name=name, points=points), doer or self.alex, pauses
        )

    def test_reclaim_pays_half_rounded_down(self):
        chore = self._burned(points=5)
        self.assertEqual(services.reclaim(chore, self.alex), 2, "5 -> 2, not 2.5")
        self.assertEqual(services.member_points(self.alex), 2)

    def test_reclaim_floors_at_one_point(self):
        chore = self._burned(name="Feed the pet", points=1)
        self.assertEqual(services.reclaim(chore, self.alex), 1)

    def test_reclaim_halves_after_the_pause_penalty(self):
        # 5 points, two pauses -> would have paid 3, so reclaiming pays 1.
        chore = self._burned(points=5, pauses=2)
        self.assertEqual(services.reclaim(chore, self.alex), 1)

    def test_reclaim_is_worse_than_claiming_first(self):
        claimed = Chore.objects.create(
            name="Mow the lawn", points=5, assigned_to=self.alex
        )
        finish(claimed, self.alex)
        burned = self._burned(name="Wash the car", points=5, doer=self.sam)
        reclaimed = services.reclaim(burned, self.sam)
        self.assertGreater(claimed.points_awarded, reclaimed)

    def test_reclaim_assigns_the_chore(self):
        chore = self._burned()
        services.reclaim(chore, self.alex)
        chore.refresh_from_db()
        self.assertEqual(chore.assigned_to, self.alex)
        self.assertEqual(chore.points_awarded, 2)

    def test_reclaim_upgrades_the_existing_row_rather_than_adding_one(self):
        chore = self._burned()
        services.reclaim(chore, self.alex)
        award = PointsAward.objects.get()
        self.assertEqual(award.points, 2)
        self.assertEqual(award.reason, AwardReason.RECLAIMED)

    def test_reclaim_does_not_double_count_the_chore(self):
        chore = self._burned(points=5, pauses=1)
        services.reclaim(chore, self.alex)
        self.assertEqual(services.clean_run_rate(self.alex), 0, "one chore, one pause")

    # --- who may not reclaim ------------------------------------------------

    def test_only_the_person_who_did_it_can_reclaim(self):
        chore = self._burned(doer=self.alex)
        with self.assertRaises(services.IllegalReclaim):
            services.reclaim(chore, self.sam)
        self.assertEqual(services.member_points(self.sam), 0)

    def test_cannot_reclaim_twice(self):
        chore = self._burned()
        services.reclaim(chore, self.alex)
        with self.assertRaises(services.IllegalReclaim):
            services.reclaim(chore, self.alex)
        self.assertEqual(services.member_points(self.alex), 2, "paid once")

    def test_cannot_reclaim_an_owned_chore(self):
        chore = Chore.objects.create(
            name="Mow the lawn", points=5, assigned_to=self.alex
        )
        finish(chore, self.alex)
        with self.assertRaises(services.IllegalReclaim):
            services.reclaim(chore, self.alex)

    def test_cannot_reclaim_an_unfinished_chore(self):
        chore = Chore.objects.create(name="Mow the lawn", points=5)
        with self.assertRaises(services.IllegalReclaim):
            services.reclaim(chore, self.alex)

    def test_can_reclaim_predicate_matches_the_rules(self):
        burned = self._burned()
        self.assertTrue(services.can_reclaim(burned, self.alex))
        self.assertFalse(services.can_reclaim(burned, self.sam))
        self.assertFalse(services.can_reclaim(burned, None))
        services.reclaim(burned, self.alex)
        self.assertFalse(services.can_reclaim(burned, self.alex))


class ReclaimViewTests(TestCase):
    def setUp(self):
        self.alex = Member.objects.create(name="Alex")
        self.sam = Member.objects.create(name="Sam")
        self.chore = Chore.objects.create(name="Mow the lawn", points=5)

    def acting_as(self, member):
        session = self.client.session
        session[ACTOR_SESSION_KEY] = member.pk
        session.save()

    def _burn(self, doer):
        self.acting_as(doer)
        self.client.post(reverse("chore_action", args=[self.chore.pk, "start"]))
        self.client.post(reverse("chore_action", args=[self.chore.pk, "finish"]))

    def test_history_offers_reclaim_to_the_doer(self):
        self._burn(self.alex)
        page = self.client.get(reverse("history"))
        self.assertContains(page, "Reclaim")

    def test_history_does_not_offer_reclaim_to_anyone_else(self):
        self._burn(self.alex)
        self.acting_as(self.sam)
        page = self.client.get(reverse("history"))
        self.assertNotContains(page, "Reclaim")

    def test_reclaim_over_http_awards_half(self):
        self._burn(self.alex)
        response = self.client.post(
            reverse("chore_action", args=[self.chore.pk, "reclaim"]),
            {"next": reverse("history")},
        )
        self.assertRedirects(response, reverse("history"))
        self.chore.refresh_from_db()
        self.assertEqual(self.chore.points_awarded, 2)
        self.assertEqual(self.chore.assigned_to, self.alex)
        self.assertEqual(services.member_points(self.alex), 2)

    def test_reclaim_by_the_wrong_person_changes_nothing(self):
        self._burn(self.alex)
        self.acting_as(self.sam)
        response = self.client.post(
            reverse("chore_action", args=[self.chore.pk, "reclaim"])
        )
        self.assertEqual(response.status_code, 302)
        self.chore.refresh_from_db()
        self.assertEqual(self.chore.points_awarded, 0)
        self.assertEqual(services.member_points(self.sam), 0)

    def test_deleted_chore_still_shows_in_history(self):
        chore = Chore.objects.create(
            name="Wash the car", points=4, assigned_to=self.alex
        )
        self.acting_as(self.alex)
        self.client.post(reverse("chore_action", args=[chore.pk, "start"]))
        self.client.post(reverse("chore_action", args=[chore.pk, "finish"]))
        self.client.post(reverse("chore_delete", args=[chore.pk]))

        page = self.client.get(reverse("history"))
        self.assertContains(page, "Wash the car")
        self.assertContains(page, "chore deleted")


class DeleteViewTests(TestCase):
    def setUp(self):
        self.alex = Member.objects.create(name="Alex")

    def test_get_shows_confirmation_without_deleting(self):
        chore = Chore.objects.create(name="Iron a batch", points=3)
        response = self.client.get(reverse("chore_delete", args=[chore.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(Chore.objects.filter(pk=chore.pk).exists())

    def test_post_deletes_and_redirects(self):
        chore = Chore.objects.create(name="Iron a batch", points=3)
        response = self.client.post(reverse("chore_delete", args=[chore.pk]))
        self.assertRedirects(response, reverse("dashboard"))
        self.assertFalse(Chore.objects.filter(pk=chore.pk).exists())

    def test_delete_url_is_not_swallowed_by_the_action_route(self):
        chore = Chore.objects.create(name="Iron a batch", points=3)
        self.client.post(reverse("chore_delete", args=[chore.pk]))
        self.assertFalse(Chore.objects.filter(pk=chore.pk).exists())

    def test_unknown_chore_404s(self):
        self.assertEqual(
            self.client.get(reverse("chore_delete", args=[999])).status_code, 404
        )

    def test_deleting_a_recurrence_parent_leaves_the_successor(self):
        chore = Chore.objects.create(
            name="Bins out to the curb", points=1, assigned_to=self.alex,
            due_at=timezone.now(), recurrence="daily",
        )
        finish(chore, self.alex)
        successor = Chore.objects.get(recurrence_parent=chore)
        chore.delete()
        successor.refresh_from_db()
        self.assertIsNone(successor.recurrence_parent, "orphaned, not deleted")
        self.assertEqual(successor.status, Status.PENDING)


class ReclaimSnapshotTests(TestCase):
    """Point values are fixed when the work is done, reclaims included."""

    def setUp(self):
        self.alex = Member.objects.create(name="Alex")

    def _burned(self, points=5, pauses=0):
        return finish(
            Chore.objects.create(name="Mow the lawn", points=points), self.alex, pauses
        )

    def test_completion_snapshots_what_the_chore_was_worth(self):
        self._burned(points=5)
        self.assertEqual(PointsAward.objects.get().chore_points, 5)

    def test_repricing_the_chore_does_not_change_what_reclaiming_pays(self):
        chore = self._burned(points=5)
        chore.points = 100
        chore.save()

        self.assertEqual(services.reclaim(chore, self.alex), 2, "still a 5-pointer")
        self.assertEqual(services.member_points(self.alex), 2)

    def test_repricing_downwards_does_not_change_it_either(self):
        chore = self._burned(points=5, pauses=1)
        chore.points = 1
        chore.save()

        # 5 points less one pause is 4, so reclaiming pays 2.
        self.assertEqual(services.reclaim(chore, self.alex), 2)
