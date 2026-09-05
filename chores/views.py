from django.contrib import messages
from django.http import HttpResponseNotAllowed
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.http import url_has_allowed_host_and_scheme

from . import services
from .forms import ChoreForm
from .models import Category, Chore, Member, PointsAward, Status

ACTOR_SESSION_KEY = "actor_id"


def current_member(request):
    """Who is using the app right now. The household shares one screen."""
    member_id = request.session.get(ACTOR_SESSION_KEY)
    if not member_id:
        return None
    return Member.objects.filter(pk=member_id, is_active=True).first()


def _safe_next(request):
    """Where to send the user back to. `next` is user input, so vet it."""
    target = request.POST.get("next")
    # It has to be a path: the host check passes anything that looks like a view
    # name, and redirect() would then try to reverse "oops" and 500.
    is_path = bool(target) and target.startswith("/")
    if is_path and url_has_allowed_host_and_scheme(
        target, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        return target
    return "dashboard"


def set_actor(request):
    member_id = request.POST.get("member") or None
    if member_id and member_id.isdigit():
        request.session[ACTOR_SESSION_KEY] = int(member_id)
    else:
        request.session.pop(ACTOR_SESSION_KEY, None)
    return redirect(_safe_next(request))


def _base_context(request):
    return {
        "members": Member.objects.filter(is_active=True),
        "actor": current_member(request),
    }


def _decorate(chores):
    """Attach the actions each chore will accept, for the buttons."""
    for chore in chores:
        chore.actions = services.available_actions(chore)
    return chores


DASHBOARD_ORDER = ["overdue", "today", "in_progress", "pool", "undated"]


def dashboard(request):
    buckets = services.dashboard()
    context = _base_context(request)
    context.update(_first_bucket_wins(buckets, DASHBOARD_ORDER))
    context["leaderboard"] = services.leaderboard()
    return render(request, "chores/dashboard.html", context)


def _first_bucket_wins(buckets, order):
    """The buckets overlap; each chore is rendered once, in the first it lands in."""
    seen = set()
    picked = {}
    for name in order:
        chores = [chore for chore in buckets[name] if chore.pk not in seen]
        seen.update(chore.pk for chore in chores)
        picked[name] = _decorate(chores)
    return picked


def chore_list(request):
    chores = (
        Chore.objects.exclude(status=Status.COMPLETED)
        .select_related("assigned_to")
        .with_pause_count()
    )
    member_id = request.GET.get("member")
    category = request.GET.get("category")
    if member_id:
        chores = chores.filter(assigned_to_id=member_id)
    if category:
        chores = chores.filter(category=category)

    context = _base_context(request)
    context.update(
        {
            "chores": _decorate(list(chores)),
            "categories": Category.choices,
            "selected_member": member_id,
            "selected_category": category,
        }
    )
    return render(request, "chores/chore_list.html", context)


def chore_new(request):
    # Bind on the method, not on truthiness: an empty POST is still a POST and
    # has to come back with errors rather than silently doing nothing.
    form = ChoreForm(request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        chore = form.save()
        messages.success(request, f"Added “{chore.name}”.")
        return redirect("dashboard")
    context = _base_context(request)
    context.update({"form": form, "heading": "Add a chore"})
    return render(request, "chores/chore_form.html", context)


def chore_edit(request, pk):
    chore = get_object_or_404(Chore, pk=pk)
    form = ChoreForm(
        request.POST if request.method == "POST" else None, instance=chore
    )
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, f"Updated “{chore.name}”.")
        return redirect("dashboard")
    context = _base_context(request)
    context.update({"form": form, "chore": chore, "heading": "Edit chore"})
    return render(request, "chores/chore_form.html", context)


def chore_delete(request, pk):
    """Remove a chore. GET confirms, POST deletes; its events go with it."""
    chore = get_object_or_404(Chore, pk=pk)
    if request.method == "POST":
        name = chore.name
        chore.delete()
        messages.success(request, f"Deleted “{name}”.")
        return redirect("dashboard")
    context = _base_context(request)
    context.update({"chore": chore})
    return render(request, "chores/chore_confirm_delete.html", context)


def chore_action(request, pk, action):
    """POST-only lifecycle moves, plus claiming a pool chore."""
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])

    chore = get_object_or_404(Chore, pk=pk)
    actor = current_member(request)
    back = _safe_next(request)

    if action == "reclaim":
        if actor is None:
            messages.error(request, "Say who you are first.")
        else:
            try:
                points = services.reclaim(chore, actor)
            except services.IllegalReclaim as exc:
                messages.error(request, str(exc))
            else:
                messages.success(
                    request,
                    f"{actor} reclaimed “{chore.name}” — {points} "
                    f"point{'s' if points != 1 else ''}, half rate for claiming late.",
                )
        return redirect(back)

    if action == "claim":
        if actor is None:
            messages.error(request, "Say who you are first, then claim a chore.")
        else:
            try:
                services.claim(chore, actor)
            except services.IllegalClaim as exc:
                messages.error(request, str(exc))
            else:
                messages.success(request, f"{actor} claimed “{chore.name}”.")
        return redirect(back)

    # Nobody to credit and nobody on the hook: the completion would go
    # unledgered, so refuse the work rather than lose it.
    if action in ("start", "finish") and actor is None and chore.assigned_to_id is None:
        messages.error(request, "Say who you are first.")
        return redirect(back)

    try:
        services.transition(chore, action, actor=actor)
    except services.IllegalTransition as exc:
        messages.error(request, str(exc))
        return redirect(back)
    except KeyError:
        messages.error(request, "Unknown action.")
        return redirect(back)

    if action == "finish":
        if chore.points_awarded:
            messages.success(
                request,
                f"“{chore.name}” done — {chore.points_awarded} "
                f"point{'s' if chore.points_awarded != 1 else ''} to "
                f"{chore.completed_by}.",
            )
        else:
            messages.warning(
                request,
                f"“{chore.name}” done, but nobody owned it — "
                "its points were burned.",
            )
    return redirect(back)


def member_detail(request, pk):
    member = get_object_or_404(Member, pk=pk)
    context = _base_context(request)
    context.update(
        {
            "member": member,
            "open_chores": _decorate(
                list(
                    member.chores.exclude(status=Status.COMPLETED)
                    .select_related("assigned_to")
                    .with_pause_count()
                )
            ),
            "points": services.member_points(member),
            "streak": services.streak(member),
            "clean_run_rate": services.clean_run_rate(member),
            "recent": member.awards.select_related("chore")[:10],
        }
    )
    return render(request, "chores/member_detail.html", context)


def history(request):
    """Paid work comes from the ledger, so deleting a chore cannot erase it."""
    awards = PointsAward.objects.select_related("member", "chore")
    burned = (
        Chore.objects.filter(
            status=Status.COMPLETED, assigned_to__isnull=True, points_awarded=0
        )
        .select_related("completed_by")
        .order_by("-completed_at")
    )
    member_id = request.GET.get("member")
    if member_id:
        awards = awards.filter(member_id=member_id)
        burned = burned.filter(completed_by_id=member_id)

    actor = current_member(request)
    burned = list(burned[:50])
    for chore in burned:
        chore.reclaimable = services.can_reclaim(chore, actor)

    context = _base_context(request)
    context.update(
        {
            "awards": awards[:100],
            "burned": burned,
            "selected_member": member_id,
        }
    )
    return render(request, "chores/history.html", context)
