"""Populate a believable household so the dashboard has something to show."""

import random
from datetime import datetime, time, timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from chores import services
from chores.catalog import CATALOG
from chores.models import Chore, ChoreEvent, Member, PointsAward, Recurrence, Status


class Command(BaseCommand):
    help = "Create demo members, chores and completion history."

    def handle(self, *args, **options):
        ChoreEvent.objects.all().delete()
        Chore.objects.all().delete()
        Member.objects.all().delete()

        people = [
            Member.objects.create(name="Alex"),
            Member.objects.create(name="Sam"),
            Member.objects.create(name="Rosie", is_child=True),
            Member.objects.create(name="Theo", is_child=True),
        ]
        now = timezone.now()
        rng = random.Random(7)
        pool = list(CATALOG)
        rng.shuffle(pool)

        # A backlog of completions so points, streaks and history are populated.
        today = timezone.localdate()
        for days_ago in range(14, 0, -1):
            day = today - timedelta(days=days_ago)
            for index, member in enumerate(people):
                # The first two people keep a live streak; the rest are patchy.
                keeps_streak = index < 2 and days_ago <= 5
                if not keeps_streak and rng.random() >= 0.55:
                    continue
                category, name, points = rng.choice(pool)
                # Anchor to a real local date: subtracting hours from "now"
                # can slide a completion across midnight and break the streak.
                when = timezone.make_aware(
                    datetime.combine(day, time(hour=rng.randint(8, 20)))
                )
                chore = Chore.objects.create(
                    name=name, category=category, points=points,
                    assigned_to=member, due_at=when,
                )
                services.transition(chore, "start", actor=member)
                if rng.random() < 0.3:
                    services.transition(chore, "pause", actor=member)
                    services.transition(chore, "resume", actor=member)
                services.transition(chore, "finish", actor=member)
                # Backdate both sides: streaks read the ledger, not the chore.
                Chore.objects.filter(pk=chore.pk).update(completed_at=when)
                PointsAward.objects.filter(chore=chore).update(awarded_at=when)

        # Live board: overdue, due today, recurring, and an unclaimed pool.
        board = [
            ("overdue", -2), ("overdue", -1),
            ("today", 3), ("today", 6), ("today", 9),
            ("later", 30), ("later", 55),
        ]
        for kind, offset in board:
            category, name, points = pool.pop()
            due = now + (timedelta(days=offset) if kind == "later"
                         else timedelta(hours=offset))
            Chore.objects.create(
                name=name, category=category, points=points, due_at=due,
                assigned_to=rng.choice(people),
                recurrence=Recurrence.WEEKLY if kind == "later" else Recurrence.NONE,
            )

        for _ in range(4):
            category, name, points = pool.pop()
            Chore.objects.create(
                name=name, category=category, points=points,
                due_at=now + timedelta(hours=rng.randint(2, 20)),
            )

        # Leave one chore mid-flight so the paused state is visible on the board.
        in_progress = Chore.objects.filter(
            assigned_to__isnull=False, status=Status.PENDING
        ).first()
        if in_progress:
            services.transition(in_progress, "start", actor=in_progress.assigned_to)
            services.transition(in_progress, "pause", actor=in_progress.assigned_to)

        self.stdout.write(
            self.style.SUCCESS(
                f"Demo ready: {Member.objects.count()} members, "
                f"{Chore.objects.count()} chores."
            )
        )
