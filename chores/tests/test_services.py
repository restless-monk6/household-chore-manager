from datetime import datetime, timedelta
from unittest import mock

from django.test import TestCase, override_settings
from django.utils import timezone

from chores import services
from chores.models import (
    Chore,
    EventKind,
    Member,
    PointsAward,
    Recurrence,
    Status,
)


class TransitionTests(TestCase):
    def setUp(self):
        self.member = Member.objects.create(name="Alex")
        self.chore = Chore.objects.create(
            name="Mow the lawn", points=5, assigned_to=self.member
        )

    def test_start_moves_pending_to_in_progress(self):
        services.transition(self.chore, "start", actor=self.member)
        self.assertEqual(self.chore.status, Status.IN_PROGRESS)

    def test_pause_then_resume_returns_to_in_progress(self):
        services.transition(self.chore, "start", actor=self.member)
        services.transition(self.chore, "pause", actor=self.member)
        self.assertEqual(self.chore.status, Status.PAUSED)
        services.transition(self.chore, "resume", actor=self.member)
        self.assertEqual(self.chore.status, Status.IN_PROGRESS)

    def test_illegal_transition_raises(self):
        with self.assertRaises(services.IllegalTransition):
            services.transition(self.chore, "pause", actor=self.member)

    def test_completed_is_terminal(self):
        services.transition(self.chore, "start", actor=self.member)
        services.transition(self.chore, "finish", actor=self.member)
        for action in ["start", "pause", "resume", "finish"]:
            with self.assertRaises(services.IllegalTransition):
                services.transition(self.chore, action, actor=self.member)

    def test_each_transition_writes_exactly_one_event(self):
        services.transition(self.chore, "start", actor=self.member)
        services.transition(self.chore, "pause", actor=self.member)
        self.assertEqual(self.chore.events.count(), 2)
        self.assertEqual(
            list(self.chore.events.values_list("kind", flat=True)),
            [EventKind.STARTED, EventKind.PAUSED],
        )

    def test_status_cache_matches_last_event(self):
        services.transition(self.chore, "start", actor=self.member)
        reloaded = Chore.objects.get(pk=self.chore.pk)
        self.assertEqual(reloaded.status, Status.IN_PROGRESS)


class RecurrenceTests(TestCase):
    def setUp(self):
        self.member = Member.objects.create(name="Sam")
        self.due = timezone.now()

    def _finish(self, recurrence):
        chore = Chore.objects.create(
            name="Bins out to the curb",
            points=1,
            assigned_to=self.member,
            due_at=self.due,
            recurrence=recurrence,
        )
        services.transition(chore, "start", actor=self.member)
        services.transition(chore, "finish", actor=self.member)
        return chore

    def test_daily_recurrence_spawns_next_day(self):
        chore = self._finish(Recurrence.DAILY)
        successor = Chore.objects.get(recurrence_parent=chore)
        self.assertEqual(successor.due_at, self.due + timedelta(days=1))

    def test_weekly_advances_seven_days(self):
        chore = self._finish(Recurrence.WEEKLY)
        successor = Chore.objects.get(recurrence_parent=chore)
        self.assertEqual(successor.due_at, self.due + timedelta(days=7))

    def test_monthly_clamps_to_short_months(self):
        jan31 = timezone.make_aware(datetime(2026, 1, 31, 9, 0))
        nxt = services.next_due(jan31, Recurrence.MONTHLY)
        self.assertEqual(nxt.date().isoformat(), "2026-02-28")

    def test_non_recurring_spawns_nothing(self):
        chore = self._finish(Recurrence.NONE)
        self.assertFalse(Chore.objects.filter(recurrence_parent=chore).exists())

    def test_successor_starts_pending_and_unscored(self):
        chore = self._finish(Recurrence.DAILY)
        successor = Chore.objects.get(recurrence_parent=chore)
        self.assertEqual(successor.status, Status.PENDING)
        self.assertIsNone(successor.points_awarded)
        self.assertIsNone(successor.completed_at)

    def test_successor_keeps_owner_and_points(self):
        chore = self._finish(Recurrence.DAILY)
        successor = Chore.objects.get(recurrence_parent=chore)
        self.assertEqual(successor.assigned_to, self.member)
        self.assertEqual(successor.points, chore.points)


class OverdueTests(TestCase):
    def test_chore_without_due_date_is_not_overdue(self):
        chore = Chore.objects.create(name="Dust surfaces", points=2)
        self.assertFalse(chore.is_overdue)

    def test_past_due_and_incomplete_is_overdue(self):
        chore = Chore.objects.create(
            name="Dust surfaces", points=2, due_at=timezone.now() - timedelta(hours=1)
        )
        self.assertTrue(chore.is_overdue)

    def test_completed_is_never_overdue(self):
        member = Member.objects.create(name="Alex")
        chore = Chore.objects.create(
            name="Dust surfaces",
            points=2,
            assigned_to=member,
            due_at=timezone.now() - timedelta(hours=1),
        )
        services.transition(chore, "start", actor=member)
        services.transition(chore, "finish", actor=member)
        self.assertFalse(chore.is_overdue)


class ClaimTests(TestCase):
    """Claiming is how a pool chore gets an owner, and that is all it is."""

    def setUp(self):
        self.alex = Member.objects.create(name="Alex")
        self.sam = Member.objects.create(name="Sam")

    def test_claiming_a_pool_chore_sets_the_owner(self):
        chore = Chore.objects.create(name="Feed the pet", points=1)
        services.claim(chore, self.alex)
        chore.refresh_from_db()
        self.assertEqual(chore.assigned_to, self.alex)

    def test_cannot_claim_a_chore_someone_else_owns(self):
        chore = Chore.objects.create(
            name="Mow the lawn", points=5, assigned_to=self.alex
        )
        with self.assertRaises(services.IllegalClaim):
            services.claim(chore, self.sam)
        chore.refresh_from_db()
        self.assertEqual(chore.assigned_to, self.alex)

    def test_cannot_claim_a_completed_chore(self):
        chore = Chore.objects.create(name="Feed the pet", points=1)
        services.transition(chore, "start", actor=self.alex)
        services.transition(chore, "finish", actor=self.alex)

        with self.assertRaises(services.IllegalClaim):
            services.claim(chore, self.sam)
        chore.refresh_from_db()
        self.assertIsNone(chore.assigned_to, "still reclaimable by whoever did it")
        self.assertTrue(services.can_reclaim(chore, self.alex))


class TransitionAtomicityTests(TestCase):
    """The event log and the status cache move together or not at all."""

    def setUp(self):
        self.member = Member.objects.create(name="Alex")
        self.chore = Chore.objects.create(
            name="Mow the lawn", points=5, assigned_to=self.member,
            due_at=timezone.now(), recurrence=Recurrence.DAILY,
        )
        services.transition(self.chore, "start", actor=self.member)

    def test_a_failed_payout_rolls_the_finish_back(self):
        with mock.patch.object(
            services, "_record_award", side_effect=RuntimeError("ledger down")
        ):
            with self.assertRaises(RuntimeError):
                services.transition(self.chore, "finish", actor=self.member)

        reloaded = Chore.objects.get(pk=self.chore.pk)
        self.assertEqual(reloaded.status, Status.IN_PROGRESS)
        self.assertIsNone(reloaded.completed_at)
        self.assertFalse(reloaded.events.filter(kind=EventKind.FINISHED).exists())
        self.assertEqual(PointsAward.objects.count(), 0)

    def test_a_failed_successor_rolls_the_finish_back(self):
        with mock.patch.object(
            services, "_spawn_successor", side_effect=RuntimeError("no successor")
        ):
            with self.assertRaises(RuntimeError):
                services.transition(self.chore, "finish", actor=self.member)

        reloaded = Chore.objects.get(pk=self.chore.pk)
        self.assertEqual(reloaded.status, Status.IN_PROGRESS)
        self.assertEqual(Chore.objects.count(), 1)
        self.assertEqual(PointsAward.objects.count(), 0)

    def test_a_finish_that_already_happened_is_not_paid_twice(self):
        # A second request holding a stale copy of the same chore.
        stale = Chore.objects.get(pk=self.chore.pk)
        services.transition(self.chore, "finish", actor=self.member)

        with self.assertRaises(services.IllegalTransition):
            services.transition(stale, "finish", actor=self.member)
        self.assertEqual(PointsAward.objects.count(), 1)
        self.assertEqual(services.member_points(self.member), 5)


class NextDueTimeZoneTests(TestCase):
    """Recurrence is calendar arithmetic, so it belongs in the household's time."""

    @override_settings(TIME_ZONE="America/New_York")
    def test_daily_keeps_the_clock_time_across_a_dst_change(self):
        # 1 Nov 2026 is when the clocks go back: +24h would land at 08:00.
        due = timezone.make_aware(datetime(2026, 10, 31, 9, 0))
        nxt = timezone.localtime(services.next_due(due, Recurrence.DAILY))
        self.assertEqual(nxt.date().isoformat(), "2026-11-01")
        self.assertEqual(nxt.hour, 9)

    @override_settings(TIME_ZONE="America/New_York")
    def test_weekly_keeps_the_clock_time_across_a_dst_change(self):
        due = timezone.make_aware(datetime(2026, 3, 5, 7, 30))
        nxt = timezone.localtime(services.next_due(due, Recurrence.WEEKLY))
        self.assertEqual(nxt.date().isoformat(), "2026-03-12")
        self.assertEqual((nxt.hour, nxt.minute), (7, 30))

    @override_settings(TIME_ZONE="Asia/Tokyo")
    def test_monthly_clamps_on_the_local_date(self):
        # 08:00 in Tokyo is still the previous day in UTC.
        due = timezone.make_aware(datetime(2026, 1, 31, 8, 0))
        nxt = timezone.localtime(services.next_due(due, Recurrence.MONTHLY))
        self.assertEqual(nxt.date().isoformat(), "2026-02-28")
        self.assertEqual(nxt.hour, 8)
