# Agent guide — Shared Household Chore Manager

A Django app for one household to track chores through their lifecycle and score
them. Read this before touching the code; it covers the things the repository
does not say out loud.

## Commands

There is no `uv` here and bare `python` hits the Microsoft Store alias. Use the
venv interpreter directly (or activate `.venv` first):

```
.\.venv\Scripts\python.exe manage.py runserver     # http://127.0.0.1:8000/
.\.venv\Scripts\python.exe manage.py test          # 134 tests, all should pass
.\.venv\Scripts\python.exe manage.py check
.\.venv\Scripts\python.exe manage.py seed_demo     # wipes and reseeds demo data
.\.venv\Scripts\python.exe manage.py seed_catalog  # 39 standard chores, idempotent
.\.venv\Scripts\python.exe manage.py send_reminders --window=daily
```

Python 3.13, Django 6.1, SQLite. `py -m venv .venv` created the environment;
`requirements.txt` is pinned.

## Layout

```
config/            settings, root urls
chores/            the only app
  models.py        Member, Chore, ChoreEvent, PointsAward, ReminderLog
  services.py      ALL chore mutation and ALL scoring lives here
  catalog.py       39 standard chores with default point values
  views.py         thin: parse request -> call a service -> render
  tests/           test_services, test_scoring, test_views,
                   test_commands, test_ledger, test_scenarios
_docs/plan.md          the original brief
_docs/architecture.md  design decisions and WHY — read this first
_docs/backlog.md       tickets CH-01..CH-20, each with its test names
```

## Domain rules

These are deliberate. Do not "simplify" them without asking.

- **Lifecycle**: `pending → in_progress ⇄ paused → completed`. `completed` is
  terminal. Every move goes through `services.transition()`, which writes a
  `ChoreEvent` and updates the cached `Chore.status`. The event log is the
  source of truth; `status` is a denormalised convenience.
- **Scoring**: `max(1, points - pause_count)`. Full value start-to-finish, one
  point per pause, floored at 1 so finishing always beats abandoning.
- **Ownership vs credit**: `assigned_to` is whose job it is; `completed_by` is
  who actually did it and who gets paid. They differ when someone covers.
- **Burned points**: finishing a chore with no owner pays 0. Claim it first to
  earn from the shared pool.
- **Reclaim**: the person recorded as `completed_by` on a burned chore may claim
  it late for `max(1, full_award // 2)` — half, deliberately worse than claiming
  up front. Only that person, only once, only while it has no owner.
- **The ledger is authoritative.** `PointsAward` holds every completion (burned
  ones at zero). Totals, streaks and clean-run rates all read it.
  `Chore.points_awarded` is a convenience copy. Deleting a chore must never
  change anyone's score — the award row survives with `chore=NULL` and a
  snapshotted `chore_name`, `chore_points` and `pauses`.

## Conventions

- Mutations belong in `services.py`, never in a view or a template. Views parse,
  call, and render.
- Points values are **snapshotted** at completion, never recomputed from the
  live chore. Editing a chore's points must not rewrite past leaderboards.
- Comments explain *why*, not *what*. Skip them when the code is obvious.
- Every behaviour change gets a test. Name it after the rule it protects
  (`test_penalty_floors_at_one_point`), not the function it calls.
- Keep changes small and focused; prefer the existing conventions over new ones.
- Add the smallest viable implementation of anything missing.

## Gotchas that have already bitten

- **Do not pipe a script into `manage.py shell`.** It runs as an interactive
  console, blank lines end blocks, and it hits the real `db.sqlite3`. Use
  `manage.py shell -c "exec(open(r'path').read())"` — and remember that a script
  which deletes rows will delete the live demo data.
- **Django 6.1 uses `MAILERS`, not `EMAIL_BACKEND`.** Setting both raises
  `ImproperlyConfigured` at startup.
- **`django.utils.timezone` no longer re-exports `datetime`/`timedelta`.**
  Import them from the stdlib.
- **URL order matters.** `chores/<int:pk>/delete/` must stay above the generic
  `chores/<int:pk>/<str:action>/`, or the catch-all swallows it.
- **`next` is user input.** It goes through `views._safe_next()`, which requires
  a leading `/` — `url_has_allowed_host_and_scheme` alone accepts `"oops"` and
  then `redirect()` raises `NoReverseMatch` and 500s.
- **`form.changed_data` is relative to the form's initial**, not "the user typed
  something". Using it to decide whether to apply a catalog default silently
  overwrote deliberately chosen values.
- **Backdating test data means backdating the ledger too.** Streaks read
  `PointsAward.awarded_at`, not `Chore.completed_at`.

## Known open items

- `TIME_ZONE` is `'UTC'` in [config/settings.py](config/settings.py). "Today"
  and streak boundaries key off it; set the household's real zone. Recurrence
  arithmetic already converts to local time before advancing dates.
- `services._finish()` skips the ledger when a chore has neither an actor nor an
  owner. The views block that path, but a shell or admin completion can still go
  unrecorded. Fixing it properly means raising in `_finish` or making
  `PointsAward.member` nullable.
- `services.dashboard()["upcoming"]` is computed and never rendered.
- Deferred by design: the challenge board, per-person logins, a REST API,
  multi-household, and any background worker. See the end of
  [_docs/architecture.md](_docs/architecture.md).

## Secrets

`SECRET_KEY`, `DEBUG` and `ALLOWED_HOSTS` read from the environment with
local-dev defaults. Never commit a real key — the repository is public.
