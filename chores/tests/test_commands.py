from datetime import timedelta
from io import StringIO
from unittest import mock

from django.core import mail
from django.core.management import CommandError, call_command
from django.test import TestCase
from django.utils import timezone

from chores.catalog import CATALOG
from chores.models import Category, Chore, Member, ReminderLog


class SeedCatalogTests(TestCase):
    def test_seed_creates_catalog_chores(self):
        call_command("seed_catalog", stdout=StringIO())
        self.assertEqual(Chore.objects.count(), len(CATALOG))

    def test_seed_is_idempotent(self):
        call_command("seed_catalog", stdout=StringIO())
        call_command("seed_catalog", stdout=StringIO())
        self.assertEqual(Chore.objects.count(), len(CATALOG))

    def test_every_catalog_entry_scores_1_to_5(self):
        for _, name, points in CATALOG:
            with self.subTest(name=name):
                self.assertIn(points, range(1, 6))

    def test_every_catalog_entry_has_a_valid_category(self):
        valid = set(Category.values)
        for category, name, _ in CATALOG:
            with self.subTest(name=name):
                self.assertIn(category, valid)


class SendRemindersTests(TestCase):
    def setUp(self):
        self.member = Member.objects.create(name="Alex")
        self.chore = Chore.objects.create(
            name="Take out rubbish",
            points=1,
            assigned_to=self.member,
            due_at=timezone.now() - timedelta(hours=3),
        )

    def test_overdue_window_emails_once(self):
        call_command("send_reminders", window="overdue", stdout=StringIO())
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("Take out rubbish", mail.outbox[0].body)

    def test_second_run_does_not_resend(self):
        call_command("send_reminders", window="overdue", stdout=StringIO())
        call_command("send_reminders", window="overdue", stdout=StringIO())
        self.assertEqual(len(mail.outbox), 1)

    def test_nothing_due_sends_no_mail(self):
        Chore.objects.all().delete()
        call_command("send_reminders", window="overdue", stdout=StringIO())
        self.assertEqual(len(mail.outbox), 0)

    def test_unknown_window_raises(self):
        with self.assertRaises(CommandError):
            call_command("send_reminders", window="hourly", stdout=StringIO())


class SeedCatalogDuplicateTests(TestCase):
    """Nothing stops two pending chores sharing a name, so seeding must cope."""

    def test_seeding_survives_a_duplicate_pending_name(self):
        call_command("seed_catalog", stdout=StringIO())
        Chore.objects.create(name="Mow the lawn", category=Category.OUTDOOR, points=5)

        call_command("seed_catalog", stdout=StringIO())

        self.assertEqual(Chore.objects.filter(name="Mow the lawn").count(), 2)
        self.assertEqual(Chore.objects.count(), len(CATALOG) + 1)


class ReminderWindowTests(TestCase):
    """Summaries repeat; the one-shot nags do not."""

    def setUp(self):
        self.member = Member.objects.create(name="Alex")
        self.now = timezone.now()
        self.chore = Chore.objects.create(
            name="Take out rubbish",
            points=1,
            assigned_to=self.member,
            due_at=self.now - timedelta(hours=3),
        )

    def run_at(self, window, when):
        with mock.patch("django.utils.timezone.now", return_value=when):
            call_command("send_reminders", window=window, stdout=StringIO())

    def test_daily_summary_sends_once_a_day_and_again_tomorrow(self):
        call_command("send_reminders", window="daily", stdout=StringIO())
        call_command("send_reminders", window="daily", stdout=StringIO())
        self.assertEqual(len(mail.outbox), 1, "one summary a day")

        self.run_at("daily", self.now + timedelta(days=1))
        self.assertEqual(len(mail.outbox), 2, "tomorrow is a new summary")

    def test_weekly_summary_sends_once_a_week_and_again_next_week(self):
        call_command("send_reminders", window="weekly", stdout=StringIO())
        call_command("send_reminders", window="weekly", stdout=StringIO())
        self.assertEqual(len(mail.outbox), 1)

        self.run_at("weekly", self.now + timedelta(days=8))
        self.assertEqual(len(mail.outbox), 2)

    def test_weekly_looks_further_ahead_than_daily(self):
        self.chore.delete()
        Chore.objects.create(
            name="Iron a batch",
            points=3,
            assigned_to=self.member,
            due_at=self.now + timedelta(days=3),
        )
        call_command("send_reminders", window="daily", stdout=StringIO())
        self.assertEqual(len(mail.outbox), 0, "nothing due in the next 24 hours")

        call_command("send_reminders", window="weekly", stdout=StringIO())
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("Iron a batch", mail.outbox[0].body)

    def test_overdue_nag_stays_one_shot(self):
        call_command("send_reminders", window="overdue", stdout=StringIO())
        self.run_at("overdue", self.now + timedelta(days=2))
        self.assertEqual(len(mail.outbox), 1)


class ReminderFailureTests(TestCase):
    """A reminder that never went out has to stay in the queue."""

    def setUp(self):
        self.member = Member.objects.create(name="Alex")
        Chore.objects.create(
            name="Take out rubbish",
            points=1,
            assigned_to=self.member,
            due_at=timezone.now() - timedelta(hours=3),
        )

    def test_a_failed_send_is_retried_rather_than_swallowed(self):
        with mock.patch(
            "chores.management.commands.send_reminders.send_mail",
            side_effect=OSError("smtp down"),
        ):
            with self.assertRaises(OSError):
                call_command("send_reminders", window="overdue", stdout=StringIO())
        self.assertEqual(ReminderLog.objects.count(), 0, "nothing was delivered")

        call_command("send_reminders", window="overdue", stdout=StringIO())
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(ReminderLog.objects.count(), 1)
