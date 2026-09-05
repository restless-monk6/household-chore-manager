# Household Chores

A shared chore board for one family. Most chore apps track *done / not done* —
this one tracks the **work in between**, and pays you for it.

## The idea

Every chore is worth points. But you don't get them for ticking a box, you get
them for how you actually did the job:

| | |
|---|---|
| **Start to finish in one go** | Full points |
| **Each time you pause** | −1 point (never below 1 — finishing always beats quitting) |
| **Finished a chore nobody owned** | 0 points. Claim it *first* if you want paid |
| **Realised too late it was yours** | Reclaim it for half — worse than claiming up front, on purpose |

So mowing the lawn is worth 5. Mow it in one sitting and you get 5. Break off
twice for a snack and you get 3. Do it without claiming it and you get nothing —
though the app still remembers it was you, and lets you claim it late for 2.

That's the whole design: make the fair thing and the rewarding thing the same
thing.

## What's in it

- **A shared board** — overdue, due today, in progress, and an unclaimed pool
  anyone can take from
- **Real lifecycle** — start, pause, resume, finish, backed by an append-only
  event log rather than a status flag
- **Recurring chores** that spawn their next occurrence when you finish one
- **Points, streaks and a leaderboard**, plus a clean-run rate that quietly
  tracks who actually sees a job through
- **Reminders** for overdue chores and daily or weekly summaries
- **A ledger** so deleting a chore never rewrites anyone's score. Points you
  earned are history; the chore that produced them is just a row

## Running it

```bash
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt
.venv/Scripts/python.exe manage.py migrate
.venv/Scripts/python.exe manage.py seed_demo    # a household with two weeks of history
.venv/Scripts/python.exe manage.py runserver
```

Then open http://127.0.0.1:8000/, pick who you are from the header, and claim
something.

## Built with

Django 6.1, SQLite, server-rendered templates. No API, no build step, no task
queue, no JavaScript framework — one Django app, under 1,800 lines of it. The
other 1,500 lines are the **134 tests** covering the scoring rules, the
lifecycle, recurrence, deletion and reclaim.

## Reading further

The [architecture notes](_docs/architecture.md) explain every design decision
and the reasoning behind it — including the ones that turned out to be wrong.
Points started out computed on the fly with no ledger table, which was elegant
right up until deleting a finished chore silently took someone's points back.

- [_docs/plan.md](_docs/plan.md) — the original brief and scope
- [_docs/backlog.md](_docs/backlog.md) — tickets, each with the tests that close it
- [AGENT.md](AGENT.md) — the working guide for contributors
