# Architecture — Shared Household Chore Manager

Target: a single Django project, server-rendered, SQLite. No API layer, no task
queue, no frontend framework. Everything below is chosen as the smallest thing
that satisfies the plan in `_docs/plan.md`.

## Stack

| Concern | Choice | Why |
| --- | --- | --- |
| Framework | Django 6.1 | Already installed; admin + ORM + templates cover most of the scope |
| Database | SQLite | Single household, single machine, no ops |
| UI | Django templates + one CSS file | No build step, no JS framework needed |
| Auth | One shared household login (`django.contrib.auth`) | Plan says "shared family account"; members are data, not accounts |
| Reminders | Management command run by a scheduler | Avoids Celery/Redis for a job that runs once or twice a day |
| Admin | `django.contrib.admin` | Free CRUD for seeding categories/members |

## Project layout

```
manage.py
requirements.txt
config/            # settings, root urls, wsgi
chores/            # the one app
  models.py        # Member, Chore, ChoreEvent
  catalog.py       # standard chore list + default point values
  services.py      # lifecycle transitions, recurrence, scoring
  views.py         # thin: parse request -> call service -> render
  urls.py
  admin.py
  management/commands/send_reminders.py
  management/commands/seed_catalog.py
  templates/chores/
  tests/
templates/base.html
static/app.css
```

One app. Splitting into `households/`, `gamification/`, `reminders/` would add
import wiring without reducing any real complexity at this size.

## Data model

**Member** — a person in the house. `name`, `is_child`, `is_active`. This is
the model that carries multi-user identity: assignment, event attribution, and
all scoring hang off it. Dropping `Household` removed the grouping layer above
people, not people themselves.
Deliberately *not* a `User`. Multi-household is out of scope and the plan asks
for a shared family account, so nobody needs their own password. If per-person
login is wanted later, add a nullable `user = OneToOneField(User)`; no other
model changes.

There is no `Household` model. With multi-household explicitly out of scope, it
would be a table with exactly one row that every query has to filter on.

**Chore** — the unit of work *and* the unit of scheduling.

```
name, category, notes
assigned_to    -> Member (nullable; the owner: whose job this is)
due_at         (nullable)
recurrence     none | daily | weekly | monthly
points         (int, default 1)
status         pending | in_progress | paused | completed
completed_at   (nullable)
points_awarded (nullable int)
completed_by   -> Member (nullable; set at completion)
recurrence_parent -> Chore (nullable, self FK)
```

`category` is a `TextChoices` enum, not a table. Kitchen/bathroom/laundry are
fixed vocabulary; a lookup table buys nothing until users can define their own.

**ChoreEvent** — append-only log: `chore`, `kind` (started/paused/resumed/
finished), `at`, `actor -> Member`. This is the source of truth for the
completion-tracking requirement. `Chore.status` is a denormalised cache of the
last event so the dashboard can filter in SQL instead of in Python.

Active working time = sum of resumed→paused intervals, derived from the log.
Not stored.

### Two things worth calling out

*Recurrence.* No template/instance split. A recurring chore is one row; when it
is completed, `services.complete()` creates the **next** row with `due_at`
advanced and `recurrence_parent` pointing back. History stays queryable as a
normal chore list, and "what's due today" is a single `due_at` filter with no
date expansion at read time. The cost is that you cannot see future occurrences
before they exist — acceptable, since the dashboard is today/overdue-oriented.

*Points.* `points_awarded` is stamped at completion, not read from
`chore.points` at report time — otherwise editing a chore's value silently
rewrites past leaderboards. `completed_by` records who earned it. Both fields
track a chore to a person, but they answer different questions: `assigned_to`
is **ownership** (whose job it is, what shows on their list, what the reminders
chase), `completed_by` is **credit** (who actually did it). For most completed
chores they hold the same member; they differ when someone covers for another,
and the person who did the work should be the one who scores. The full rules are
below.

## Scoring rules

### Effort scale

Every chore is priced 1–5 by how long it takes, so a new chore is easy to slot in:

| Points | Effort |
| --- | --- |
| 1 | Under 5 minutes |
| 2 | 5–15 minutes |
| 3 | 15–30 minutes |
| 4 | 30–60 minutes, or unpleasant |
| 5 | An hour or more |

### Standard chore catalog

Ships in `chores/catalog.py` and is loaded by `manage.py seed_catalog`, so a new
household starts with a working board instead of an empty one. These are
defaults — `Chore.points` is editable per chore, and the form prefills from the
catalog when a name matches.

| Category | Chore | Pts |
| --- | --- | --- |
| Kitchen | Unload dishwasher | 1 |
| Kitchen | Wipe counters and table | 1 |
| Kitchen | Take out rubbish | 1 |
| Kitchen | Wash up / load dishwasher | 2 |
| Kitchen | Cook dinner | 3 |
| Kitchen | Mop kitchen floor | 3 |
| Kitchen | Clean out the fridge | 3 |
| Kitchen | Clean oven and stovetop | 4 |
| Bathroom | Wipe sink and mirror | 1 |
| Bathroom | Restock paper and soap | 1 |
| Bathroom | Mop bathroom floor | 2 |
| Bathroom | Clean the toilet | 3 |
| Bathroom | Clean shower and bath | 4 |
| Laundry | Start a load | 1 |
| Laundry | Move load to dryer / hang out | 1 |
| Laundry | Fold and put away a load | 2 |
| Laundry | Change bed sheets | 2 |
| Laundry | Iron a batch | 3 |
| Living areas | Tidy the living room | 2 |
| Living areas | Dust surfaces | 2 |
| Living areas | Vacuum one room | 2 |
| Living areas | Clean the windows | 3 |
| Living areas | Mop the floors | 3 |
| Living areas | Vacuum the whole house | 4 |
| Bedrooms | Make the bed | 1 |
| Bedrooms | Tidy your room | 2 |
| Bedrooms | Sort and put away clothes | 2 |
| Outdoor | Water the plants | 1 |
| Outdoor | Bins out to the curb | 1 |
| Outdoor | Sweep the porch or driveway | 2 |
| Outdoor | Weed the garden | 4 |
| Outdoor | Rake the leaves | 4 |
| Outdoor | Wash the car | 4 |
| Outdoor | Mow the lawn | 5 |
| Pets | Feed the pet | 1 |
| Pets | Walk the dog | 2 |
| Pets | Clean litter box or cage | 2 |
| Errands | Put away the groceries | 1 |
| Errands | Do the grocery shop | 4 |

`Chore.category` is a `TextChoices` enum over those eight categories.

### The pause penalty

Full points for start-to-finish in one session; **−1 point per pause, floored at
1**.

```
points_awarded = max(1, chore.points - pause_count)
```

`pause_count` is `ChoreEvent.objects.filter(chore=c, kind="paused").count()` —
already in the event log, nothing new to store. The rule is integer-only and
predictable enough for a child to do in their head, and it displays as its own
working: `5 pts − 2 pauses = 3 pts`.

The floor of 1 matters: a finished chore must always beat an abandoned one, or
the penalty starts arguing against the app's whole purpose. A 1-point chore is
therefore effectively pause-proof, which is fine — nothing under five minutes
should need a break.

### Reclaiming a burned chore

A chore finished while unclaimed pays nothing, but the log still records who did
it. That person — and only that person — can put their name to it afterwards and
collect **half** of what claiming first would have paid, rounded down, floored
at 1:

```
reclaim_award = max(1, max(1, points - pauses) // 2)
```

So a clean 5-pointer pays 5 claimed, 2 reclaimed. Half is deliberately worse
than claiming up front, so the incentive still points at taking the chore before
doing it rather than after. Reclaiming upgrades the existing zero-point ledger
row rather than adding a second one, so the chore is still counted once in the
clean-run rate. It can only happen once, and only while the chore has no owner.

### Unassigned chores burn their points

A chore completed while `assigned_to` is null awards **nothing** —
`points_awarded = 0`. `completed_by` is still recorded, so it appears in history
and the chore counts as done; it just does not score.

The way to earn from the shared pool is to claim it: assign it to yourself, then
do it. That is the intended path, not a loophole — it is what turns the pool
into a decision instead of a free-for-all, and it keeps the board honest about
who is on the hook for what.

Consequence worth naming: this removes the strongest argument for crediting
`completed_by` over `assigned_to`, since null owners now score zero either way.
What still separates them is covering — doing a chore assigned to someone else
— where credit follows the work.

## The points ledger

Points were originally computed straight off `Chore` rows — no ledger table,
nothing to keep in sync. That broke on a requirement that arrived later:
**deleting a completed chore must not take its points back**. Earned points are
history; the chore is just the thing that produced them. Derived totals cannot
express that, so payments moved into a table of their own.

**PointsAward** — one row per completion.

```
member       -> Member (CASCADE)
chore        -> Chore (SET_NULL: the row outlives the chore)
chore_name   snapshot, because the chore may be gone
points       what was actually paid (0 for a burned chore)
pauses       snapshot, for the clean-run rate
reason       completed | reclaimed
awarded_at
```

Every completion is ledgered, burned ones at zero. Recording only paid work
would have quietly dropped unclaimed chores out of the clean-run rate, which
measures work done, not money earned.

The cost of this change is the one the original design was avoiding: two places
now hold a number, and `Chore.points_awarded` is a convenience copy of the
ledger row. The ledger is authoritative — every total, streak and rate reads it.

## Gamification — derived from the ledger

- **Points**: `SUM(points)` over a member's awards.
- **Clean-run rate**: share of a member's chores finished with no pause — the
  pause penalty is already a number, so this comes free.
- **Streak**: distinct `awarded_at` dates per member, walked backwards from today.
- **Leaderboard**: order members by points over a date window.

All are aggregate queries in `services.py` over `PointsAward`. No denormalised
totals on `Member`: a running column has to be decremented when a completion is
undone, and it drifts the first time that is missed. The "challenge board" in
the plan is marked optional and is left out of the MVP.

## Lifecycle

```
pending --start--> in_progress --pause--> paused --resume--> in_progress
                        |                                        |
                        +----------------finish------------------+
                                         |
                                    completed  --(if recurring)--> new pending chore
```

Enforced in one place: `services.transition(chore, action, actor)`. It validates
the move against a dict of allowed transitions, writes a `ChoreEvent`, updates
`Chore.status`, and on finish stamps `completed_at` / `completed_by`, computes
`points_awarded` from the pause count, and spawns the next occurrence. Views never mutate a chore
directly. This is what keeps `views.py` boring and makes the rules testable
without HTTP.

## Views

| URL | Purpose |
| --- | --- |
| `/` | Dashboard: today, overdue, unassigned, leaderboard strip |
| `/chores/new/`, `/chores/<id>/edit/` | Create / edit |
| `/chores/<id>/<action>/` | POST-only lifecycle actions |
| `/members/<id>/` | One person's chores + points + streak |
| `/history/` | Completed chores, filterable by member and date |

"Due soon" and "overdue" are computed at request time from `due_at` and
`status`. There is no reminder state machine for the on-screen case.

## Reminders

`python manage.py send_reminders --window=due-soon|overdue|daily|weekly`, driven
by Windows Task Scheduler (or cron). It renders a summary and hands it to
Django's email backend — console backend in development, so the feature is fully
demoable with zero configuration.

A `ReminderLog(chore, kind, sent_at)` row prevents re-sending the same overdue
nag on every invocation. That is the only piece of reminder state.

## Build order

1. Project + app skeleton, `Member`, `Chore`, admin, migrations.
2. Chore CRUD + list view. (Success criteria 1–2 done.)
3. `ChoreEvent` + `services.transition` + action buttons. (Criterion 3.)
4. Dashboard: today / overdue / incomplete. (Criteria 4–5.)
5. Catalog + `seed_catalog`, points, streaks, leaderboard. (Criterion 6.)
6. `send_reminders` command.
7. History and per-member pages.

Each step is independently demoable and leaves the app working.

## Explicitly deferred

REST API, per-person logins, multi-household, real-time updates, the challenge
board, notification channels beyond email, and any background worker. Each is a
straight addition to the model above rather than a rewrite.
