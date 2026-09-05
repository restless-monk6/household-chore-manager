"""The only place chores are mutated, and the only place points are decided."""

import calendar
from collections import defaultdict
from datetime import datetime, time, timedelta
from datetime import timezone as dt_timezone

from django.db import transaction
from django.db.models import Count, Q, Sum
from django.utils import timezone

from .models import (
    AwardReason,
    Chore,
    ChoreEvent,
    EventKind,
    Member,
    PointsAward,
    Recurrence,
    Status,
)


class IllegalTransition(Exception):
    """Raised when an action is not legal from the chore's current status."""


class IllegalReclaim(Exception):
    """Raised when a chore cannot be reclaimed by this member."""


class IllegalClaim(Exception):
    """Raised when a chore is not available to be claimed."""


# (current status, action) -> new status. Anything absent is illegal, which
# makes 'completed' terminal by omission.
TRANSITIONS = {
    (Status.PENDING, "start"): Status.IN_PROGRESS,
    (Status.IN_PROGRESS, "pause"): Status.PAUSED,
    (Status.PAUSED, "resume"): Status.IN_PROGRESS,
    (Status.IN_PROGRESS, "finish"): Status.COMPLETED,
    (Status.PAUSED, "finish"): Status.COMPLETED,
}

EVENT_FOR_ACTION = {
    "start": EventKind.STARTED,
    "pause": EventKind.PAUSED,
    "resume": EventKind.RESUMED,
    "finish": EventKind.FINISHED,
}


def available_actions(chore):
    return [action for (status, action) in TRANSITIONS if status == chore.status]


def transition(chore, action, actor=None):
    """Move a chore through its lifecycle. Writes one event, updates the cache.

    All of it in one transaction: a finish that fails half way through must not
    leave a 'finished' event in the log against a chore that is still open.
    """
    with transaction.atomic():
        _lock(chore)
        try:
            new_status = TRANSITIONS[(chore.status, action)]
        except KeyError:
            raise IllegalTransition(
                f"Cannot {action} a chore that is {chore.get_status_display().lower()}."
            )

        ChoreEvent.objects.create(
            chore=chore, kind=EVENT_FOR_ACTION[action], actor=actor
        )
        chore.status = new_status

        if new_status == Status.COMPLETED:
            _finish(chore, actor)

        chore.save()
    return chore


def _lock(chore):
    """Re-read the chore with its row locked until the transaction commits.

    Two people hitting Finish at once would otherwise both read 'in progress'
    and both be paid.
    """
    chore.refresh_from_db(from_queryset=Chore.objects.select_for_update())


def _finish(chore, actor):
    """Stamp completion, award points, and spawn the next occurrence."""
    chore.completed_at = timezone.now()
    # Credit follows the work: the finisher, falling back to the owner.
    chore.completed_by = actor or chore.assigned_to
    chore.points_awarded = award_for(chore)
    if chore.completed_by:
        # Every completion is ledgered, burned ones at zero: the work happened,
        # and the record has to outlive the chore either way.
        _record_award(chore, chore.completed_by, chore.points_awarded)
    if chore.recurrence != Recurrence.NONE:
        _spawn_successor(chore)


def _record_award(chore, member, points, reason=AwardReason.COMPLETED, at=None):
    """Write the payment to the ledger, where deleting the chore cannot reach it."""
    return PointsAward.objects.create(
        member=member,
        chore=chore,
        chore_name=chore.name,
        points=points,
        chore_points=chore.points,
        pauses=chore.pause_count,
        reason=reason,
        awarded_at=at or timezone.now(),
    )


def full_award_for(chore):
    """What this chore pays a claimed owner: full value less one per pause."""
    return max(1, chore.points - chore.pause_count)


def award_for(chore):
    """Points earned by completing this chore right now.

    Full value start-to-finish, minus one per pause, floored at 1 so a finished
    chore always beats an abandoned one. An unowned chore burns its points.
    """
    if chore.assigned_to_id is None:
        return 0
    return full_award_for(chore)


def _half_rate(points, pauses):
    """Half of what claiming first would have paid, rounded down, floored at 1.

    Deliberately worse than claiming up front, so the incentive still points at
    taking the chore before doing it rather than after.
    """
    return max(1, max(1, points - pauses) // 2)


def reclaim_award_for(chore):
    """What reclaiming this chore pays, from the snapshot taken at completion.

    Not from the live chore: point values are fixed when the work is done, so
    re-pricing it afterwards cannot change what that run is worth.
    """
    award = chore.awards.order_by("id").first()
    if award is None:
        return _half_rate(chore.points, chore.pause_count)
    return _half_rate(award.chore_points, award.pauses)


def reclaim(chore, member):
    """Put your name to a chore you finished while it was still unclaimed.

    Only the person the event log says did the work can do this, only once, and
    only for a chore whose points were burned.
    """
    with transaction.atomic():
        _lock(chore)
        if chore.status != Status.COMPLETED:
            raise IllegalReclaim("Only a finished chore can be reclaimed.")
        if chore.assigned_to_id is not None:
            raise IllegalReclaim(f"“{chore.name}” already belongs to someone.")
        if chore.points_awarded:
            raise IllegalReclaim(f"“{chore.name}” has already been paid out.")
        if chore.completed_by_id != member.pk:
            raise IllegalReclaim("Only the person who did the chore can reclaim it.")

        points = reclaim_award_for(chore)
        chore.assigned_to = member
        chore.points_awarded = points
        chore.save(update_fields=["assigned_to", "points_awarded"])

        # Upgrade the zero-point row written at completion rather than adding a
        # second one, so the chore is still counted once.
        updated = PointsAward.objects.filter(chore=chore, member=member).update(
            points=points, reason=AwardReason.RECLAIMED
        )
        if not updated:
            _record_award(chore, member, points, reason=AwardReason.RECLAIMED)
    return points


def can_reclaim(chore, member):
    return (
        member is not None
        and chore.status == Status.COMPLETED
        and chore.assigned_to_id is None
        and not chore.points_awarded
        and chore.completed_by_id == member.pk
    )


def next_due(due_at, recurrence):
    """The next occurrence, kept at the same wall-clock time for the household.

    Done in local time: 'tomorrow' means the same clock time tomorrow, which is
    23 or 25 hours away across a DST change, and the calendar month a UTC stamp
    falls in is not always the one the household is living in.
    """
    if due_at is None or recurrence == Recurrence.NONE:
        return None
    local = timezone.localtime(due_at)
    if recurrence == Recurrence.DAILY:
        nxt = local + timedelta(days=1)
    elif recurrence == Recurrence.WEEKLY:
        nxt = local + timedelta(days=7)
    elif recurrence == Recurrence.MONTHLY:
        year = local.year + (local.month // 12)
        month = local.month % 12 + 1
        # Clamp so the 31st of a short month lands on its last day.
        day = min(local.day, calendar.monthrange(year, month)[1])
        nxt = local.replace(year=year, month=month, day=day)
    else:
        return None
    return nxt.astimezone(dt_timezone.utc)


def _spawn_successor(chore):
    return Chore.objects.create(
        name=chore.name,
        category=chore.category,
        notes=chore.notes,
        assigned_to=chore.assigned_to,
        due_at=next_due(chore.due_at, chore.recurrence),
        recurrence=chore.recurrence,
        points=chore.points,
        recurrence_parent=chore,
    )


def claim(chore, member):
    """Take ownership of a pool chore so that finishing it actually scores.

    Only from the pool, and only while it is still open: taking an owned chore
    would let anyone reassign anyone's work, and putting a name to a finished
    burned chore pays nobody while destroying the doer's right to reclaim it.
    """
    if chore.status == Status.COMPLETED:
        raise IllegalClaim(f"“{chore.name}” is already finished.")
    if chore.assigned_to_id is not None:
        raise IllegalClaim(f"“{chore.name}” already belongs to {chore.assigned_to}.")

    chore.assigned_to = member
    chore.save(update_fields=["assigned_to"])
    return chore


# --- Reporting -------------------------------------------------------------


def local_today():
    return timezone.localdate()


def dashboard(now=None):
    now = now or timezone.now()
    today_end = timezone.make_aware(
        datetime.combine(timezone.localdate(now), time.max),
        timezone.get_current_timezone(),
    )
    open_chores = (
        Chore.objects.exclude(status=Status.COMPLETED)
        .select_related("assigned_to")
        .with_pause_count()
    )
    return {
        "overdue": open_chores.filter(due_at__lt=now),
        "today": open_chores.filter(due_at__gte=now, due_at__lte=today_end),
        "in_progress": open_chores.filter(
            status__in=[Status.IN_PROGRESS, Status.PAUSED]
        ),
        "pool": open_chores.filter(assigned_to__isnull=True),
        "upcoming": open_chores.filter(due_at__gt=today_end),
        "undated": open_chores.filter(due_at__isnull=True),
    }


def member_points(member, since=None):
    qs = member.awards.all()
    if since:
        qs = qs.filter(awarded_at__gte=since)
    return qs.aggregate(total=Sum("points"))["total"] or 0


def streak(member, today=None):
    """Consecutive days, ending today or yesterday, with at least one completion."""
    days = {
        timezone.localtime(at).date()
        for at in member.awards.values_list("awarded_at", flat=True)
    }
    return _streak_from_days(days, today or local_today())


def _streak_from_days(days, today):
    # Yesterday still counts: today isn't over yet.
    cursor = today if today in days else today - timedelta(days=1)
    count = 0
    while cursor in days:
        count += 1
        cursor -= timedelta(days=1)
    return count


def clean_run_rate(member):
    """Share of a member's completed chores finished without a single pause."""
    counts = member.awards.aggregate(
        total=Count("id"), clean=Count("id", filter=Q(pauses=0))
    )
    return _clean_rate(counts["total"], counts["clean"])


def _clean_rate(total, clean):
    if not total:
        return None
    return round(100 * clean / total)


def leaderboard(since=None):
    """Everyone's standing in a fixed number of queries, whatever the household size."""
    members = list(Member.objects.filter(is_active=True))
    awards = PointsAward.objects.filter(member__in=members)

    scored = awards.filter(awarded_at__gte=since) if since else awards
    points = {
        row["member"]: row["total"]
        for row in scored.values("member").annotate(total=Sum("points"))
    }
    runs = {
        row["member"]: row
        for row in awards.values("member").annotate(
            total=Count("id"), clean=Count("id", filter=Q(pauses=0))
        )
    }
    days = defaultdict(set)
    for member_id, at in awards.values_list("member_id", "awarded_at"):
        days[member_id].add(timezone.localtime(at).date())

    today = local_today()
    rows = []
    for member in members:
        run = runs.get(member.pk, {})
        rows.append(
            {
                "member": member,
                "points": points.get(member.pk) or 0,
                "streak": _streak_from_days(days[member.pk], today),
                "clean_run_rate": _clean_rate(run.get("total", 0), run.get("clean", 0)),
            }
        )
    rows.sort(key=lambda r: (-r["points"], r["member"].name))
    return rows
