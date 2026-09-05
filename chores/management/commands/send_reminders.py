"""Reminder run, driven by Task Scheduler or cron. No worker process."""

from datetime import timedelta

from django.core.mail import send_mail
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from chores.models import Chore, ReminderLog, Status

WINDOWS = ["due-soon", "overdue", "daily", "weekly"]


def log_kind(window, now):
    """The de-dup key. Summaries repeat, so theirs carries the period they cover."""
    local = timezone.localtime(now)
    if window == "daily":
        return f"daily:{local.date().isoformat()}"
    if window == "weekly":
        year, week, _ = local.isocalendar()
        return f"weekly:{year}-W{week:02d}"
    # The overdue and due-soon nags are one-shot per chore, on purpose.
    return window


class Command(BaseCommand):
    help = "Email a reminder or summary for the given window."

    def add_arguments(self, parser):
        parser.add_argument("--window", default="daily")
        parser.add_argument("--to", default="household@example.com")

    def handle(self, *args, **options):
        window = options["window"]
        if window not in WINDOWS:
            raise CommandError(f"--window must be one of: {', '.join(WINDOWS)}")

        now = timezone.now()
        open_chores = Chore.objects.exclude(status=Status.COMPLETED).select_related(
            "assigned_to"
        )
        overdue = open_chores.filter(due_at__lt=now)

        def due_within(hours):
            return open_chores.filter(
                due_at__gte=now, due_at__lte=now + timedelta(hours=hours)
            )

        if window == "overdue":
            chores, subject = list(overdue), "Overdue chores"
        elif window == "due-soon":
            chores, subject = list(due_within(24)), "Chores due soon"
        elif window == "daily":
            chores = list(overdue) + list(due_within(24))
            subject = "Chore summary"
        else:
            chores = list(overdue) + list(due_within(7 * 24))
            subject = "Chore summary for the week"

        # One nag per chore per window: ReminderLog is the whole de-dup mechanism.
        # The summaries carry their period, or the first day's send is the last.
        kind = log_kind(window, now)
        already = set(
            ReminderLog.objects.filter(kind=kind, chore__in=chores).values_list(
                "chore_id", flat=True
            )
        )
        fresh = [chore for chore in chores if chore.pk not in already]

        if not fresh:
            self.stdout.write("Nothing to send.")
            return

        lines = []
        for chore in fresh:
            who = chore.assigned_to or "unclaimed"
            when = chore.due_at.strftime("%a %d %b %H:%M") if chore.due_at else "no due date"
            flag = "OVERDUE" if chore.is_overdue else "due"
            lines.append(f"- {chore.name} ({who}) - {flag} {when}")

        # Log only what actually went out: a send that raises has to stay
        # retryable rather than being marked as delivered.
        send_mail(
            subject=f"{subject}: {len(fresh)}",
            message="\n".join(lines),
            from_email="chores@example.com",
            recipient_list=[options["to"]],
        )
        ReminderLog.objects.bulk_create(
            [ReminderLog(chore=chore, kind=kind) for chore in fresh]
        )
        self.stdout.write(self.style.SUCCESS(f"Sent {len(fresh)} reminder(s)."))
