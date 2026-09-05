from django.db import models
from django.db.models import Count, Q
from django.utils import timezone


class Member(models.Model):
    """A person in the house. Not a Django User: the household shares one login."""

    name = models.CharField(max_length=60, unique=True)
    is_child = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Category(models.TextChoices):
    KITCHEN = "kitchen", "Kitchen"
    BATHROOM = "bathroom", "Bathroom"
    LAUNDRY = "laundry", "Laundry"
    LIVING = "living", "Living areas"
    BEDROOMS = "bedrooms", "Bedrooms"
    OUTDOOR = "outdoor", "Outdoor"
    PETS = "pets", "Pets"
    ERRANDS = "errands", "Errands"


class Status(models.TextChoices):
    PENDING = "pending", "Pending"
    IN_PROGRESS = "in_progress", "In progress"
    PAUSED = "paused", "Paused"
    COMPLETED = "completed", "Completed"


class Recurrence(models.TextChoices):
    NONE = "none", "One-off"
    DAILY = "daily", "Daily"
    WEEKLY = "weekly", "Weekly"
    MONTHLY = "monthly", "Monthly"


class ChoreQuerySet(models.QuerySet):
    def with_pause_count(self):
        """Pull the pause count into the list query instead of one COUNT per row."""
        return self.annotate(
            _pause_count=Count("events", filter=Q(events__kind=EventKind.PAUSED))
        )


class Chore(models.Model):
    """The unit of work and the unit of scheduling."""

    name = models.CharField(max_length=120)
    category = models.CharField(
        max_length=20, choices=Category.choices, default=Category.KITCHEN
    )
    notes = models.TextField(blank=True)

    # Ownership: whose job this is. Null means it sits in the shared pool.
    assigned_to = models.ForeignKey(
        Member, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="chores",
    )
    due_at = models.DateTimeField(null=True, blank=True)
    recurrence = models.CharField(
        max_length=10, choices=Recurrence.choices, default=Recurrence.NONE
    )
    points = models.PositiveSmallIntegerField(default=1)

    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.PENDING
    )
    completed_at = models.DateTimeField(null=True, blank=True)
    # Credit: who actually did it. Stamped at completion, may differ from owner.
    completed_by = models.ForeignKey(
        Member, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="completions",
    )
    points_awarded = models.PositiveSmallIntegerField(null=True, blank=True)

    recurrence_parent = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="successors",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    objects = ChoreQuerySet.as_manager()

    class Meta:
        ordering = ["due_at", "name"]

    def __str__(self):
        return self.name

    @property
    def is_open(self):
        return self.status != Status.COMPLETED

    @property
    def is_overdue(self):
        # A chore with no due date can never be overdue.
        if self.due_at is None or not self.is_open:
            return False
        return self.due_at < timezone.now()

    @property
    def pause_count(self):
        # Lists annotate this; a lone instance still has to go and count.
        annotated = getattr(self, "_pause_count", None)
        if annotated is not None:
            return annotated
        return self.events.filter(kind=EventKind.PAUSED).count()


class EventKind(models.TextChoices):
    STARTED = "started", "Started"
    PAUSED = "paused", "Paused"
    RESUMED = "resumed", "Resumed"
    FINISHED = "finished", "Finished"


class ChoreEvent(models.Model):
    """Append-only log. The source of truth for completion tracking."""

    chore = models.ForeignKey(Chore, on_delete=models.CASCADE, related_name="events")
    kind = models.CharField(max_length=20, choices=EventKind.choices)
    at = models.DateTimeField(default=timezone.now)
    actor = models.ForeignKey(
        Member, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="events",
    )

    class Meta:
        ordering = ["at", "id"]

    def __str__(self):
        return f"{self.chore} {self.kind}"


class AwardReason(models.TextChoices):
    COMPLETED = "completed", "Completed"
    RECLAIMED = "reclaimed", "Reclaimed"


class PointsAward(models.Model):
    """A point payment, recorded once and kept.

    Points used to be summed straight off Chore rows, which meant deleting a
    finished chore silently rewound someone's score. Earned points are history,
    so they live in their own row and outlive the chore that produced them.
    """

    member = models.ForeignKey(
        Member, on_delete=models.CASCADE, related_name="awards"
    )
    chore = models.ForeignKey(
        Chore, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="awards",
    )
    # Snapshot: the chore may be deleted out from under this row.
    chore_name = models.CharField(max_length=120)
    points = models.PositiveSmallIntegerField()
    # Snapshot: what the chore was worth when it was finished. Reclaiming reads
    # this, so re-pricing the chore afterwards cannot rewrite what a past run pays.
    chore_points = models.PositiveSmallIntegerField(default=0)
    pauses = models.PositiveSmallIntegerField(default=0)
    reason = models.CharField(
        max_length=20, choices=AwardReason.choices, default=AwardReason.COMPLETED
    )
    awarded_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-awarded_at", "-id"]

    def __str__(self):
        return f"{self.member} +{self.points} ({self.chore_name})"


class ReminderLog(models.Model):
    """Stops the same nag being sent on every scheduler run."""

    chore = models.ForeignKey(Chore, on_delete=models.CASCADE, related_name="reminders")
    kind = models.CharField(max_length=20)
    sent_at = models.DateTimeField(default=timezone.now)

    class Meta:
        unique_together = [("chore", "kind")]
