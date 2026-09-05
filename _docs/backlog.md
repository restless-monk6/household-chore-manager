# Backlog — Shared Household Chore Manager

Tickets to build the app in `_docs/architecture.md` against the scope in
`_docs/plan.md`. Ordered; each one leaves the app working and demoable.

Every ticket lists its acceptance tests by name. Those names are the actual
`django.test.TestCase` methods to write — a ticket is done when its tests exist
and `python manage.py test` is green.

Test files: `chores/tests/test_models.py`, `test_services.py`, `test_views.py`,
`test_scoring.py`, `test_commands.py`.

---

## M1 — Foundation

### CH-01 · Project skeleton
`config/` project, `chores/` app, `base.html`, `static/app.css`, SQLite settings.

- `test_check_passes` — `manage.py check` reports no issues
- `test_dashboard_url_resolves` — `/` returns 200 with the base layout

### CH-02 · Member model
`name`, `is_child`, `is_active`. Registered in admin.

- `test_member_defaults` — new member is active, not a child
- `test_member_str` — renders the name
- `test_member_registered_in_admin`

### CH-03 · Chore model and category enum
All fields per architecture, plus migrations. Admin registration.

- `test_chore_defaults` — status `pending`, points 1, `completed_at` /
  `completed_by` / `points_awarded` all null
- `test_chore_allows_no_owner` — `assigned_to` may be null
- `test_category_choices` — the eight categories are the only valid values
- `test_chore_str`

## M2 — Chore CRUD *(success criteria 1–2)*

### CH-04 · Create and edit views
`/chores/new/`, `/chores/<id>/edit/` with a `ModelForm`.

- `test_create_valid_redirects_and_persists`
- `test_create_invalid_rerenders_with_errors` — blank name is rejected
- `test_create_prefills_points_from_catalog` — a name matching the catalog
  suggests its point value
- `test_edit_updates_existing_without_creating_a_row`

### CH-05 · Chore list
All open chores, filterable by member and category.

- `test_list_shows_open_chores`
- `test_list_excludes_completed`
- `test_list_filters_by_member`
- `test_list_empty_state`

## M3 — Lifecycle *(success criterion 3)*

### CH-06 · ChoreEvent model
Append-only log: `chore`, `kind`, `at`, `actor`.

- `test_event_ordering_is_chronological`
- `test_events_survive_chore_edit`

### CH-07 · `services.transition()`
The single mutation point. Validates against the allowed-transition table,
writes an event, updates the cached `Chore.status`.

- `test_start_moves_pending_to_in_progress`
- `test_pause_then_resume_returns_to_in_progress`
- `test_illegal_transition_raises` — pausing a `pending` chore is refused
- `test_completed_is_terminal` — no action moves a completed chore
- `test_each_transition_writes_exactly_one_event`
- `test_status_cache_matches_last_event`

### CH-08 · Lifecycle action views
`POST /chores/<id>/<action>/`, one button per legal action.

- `test_get_is_rejected` — 405, state unchanged
- `test_unknown_action_404s`
- `test_illegal_transition_shows_message_not_500`
- `test_action_redirects_back_to_referring_page`

## M4 — Dashboard *(success criteria 4–5)*

### CH-09 · Dashboard buckets
Today, overdue, unassigned pool, in-progress.

- `test_due_today_appears_in_today`
- `test_past_due_and_incomplete_is_overdue`
- `test_completed_never_appears_in_overdue`
- `test_chore_without_due_date_is_not_overdue`
- `test_unowned_chores_listed_in_pool`
- `test_buckets_use_local_date_not_utc`

## M5 — Scoring and gamification *(success criterion 6)*

### CH-10 · Catalog and `seed_catalog`
`chores/catalog.py` plus the management command.

- `test_seed_creates_catalog_chores`
- `test_seed_is_idempotent` — running twice creates no duplicates
- `test_every_catalog_entry_scores_1_to_5`
- `test_every_catalog_entry_has_a_valid_category`

### CH-11 · Award points on completion
`points_awarded = max(1, points - pause_count)`; 0 when unowned.

- `test_clean_run_awards_full_points`
- `test_each_pause_costs_one_point`
- `test_penalty_floors_at_one_point`
- `test_unassigned_chore_awards_zero`
- `test_unassigned_chore_still_records_completed_by`
- `test_completed_by_is_the_finisher_not_the_owner`
- `test_editing_points_later_does_not_change_past_awards`

### CH-12 · Points, streaks, leaderboard
Aggregates in `services.py`; leaderboard strip on the dashboard.

- `test_member_total_sums_awarded_points`
- `test_zero_point_completions_do_not_inflate_totals`
- `test_streak_counts_consecutive_days`
- `test_streak_breaks_on_a_missed_day`
- `test_two_chores_same_day_count_as_one_streak_day`
- `test_leaderboard_orders_by_points_in_window`

### CH-13 · Recurrence
On completion, a recurring chore spawns its successor.

- `test_daily_recurrence_spawns_next_day`
- `test_weekly_and_monthly_advance_correctly`
- `test_non_recurring_spawns_nothing`
- `test_successor_links_to_recurrence_parent`
- `test_successor_starts_pending_and_unscored`
- `test_successor_keeps_owner_and_points`

## M6 — Reminders

### CH-14 · `send_reminders` command
`--window=due-soon|overdue|daily|weekly`, plus `ReminderLog` de-duplication.

- `test_overdue_window_emails_once`
- `test_second_run_does_not_resend` — `ReminderLog` suppresses the repeat
- `test_nothing_due_sends_no_mail`
- `test_daily_summary_lists_today_and_overdue`
- `test_unknown_window_exits_nonzero`

## M7 — Reporting

### CH-15 · Completion history
`/history/`, filterable by member and date range.

- `test_history_lists_completed_only`
- `test_history_filters_by_member_and_range`
- `test_history_shows_points_and_pause_count`

### CH-16 · Member detail
`/members/<id>/` — their chores, points, streak, clean-run rate.

- `test_member_page_shows_owned_open_chores`
- `test_member_page_shows_points_and_streak`
- `test_member_page_404s_for_unknown_member`

## M8 — Removal and the points ledger

Added after the first build: testing "remove a chore" found there was no way to
do it outside the admin, and removing a completed one silently rewound its
points.

### CH-17 · Delete a chore
`GET /chores/<id>/delete/` confirms, `POST` deletes. Linked from the edit form.

- `test_get_shows_confirmation_without_deleting`
- `test_post_deletes_and_redirects`
- `test_delete_url_is_not_swallowed_by_the_action_route`
- `test_unknown_chore_404s`
- `test_removing_a_started_chore_removes_its_events_too`
- `test_deleting_a_recurrence_parent_leaves_the_successor`

### CH-18 · `PointsAward` ledger
Points move out of `Chore` and into their own table, so deleting a finished
chore cannot take them back.

- `test_completion_writes_one_ledger_row`
- `test_deleting_the_chore_keeps_the_points`
- `test_deleting_the_chore_keeps_the_streak`
- `test_deleting_an_unstarted_chore_leaves_no_trace`
- `test_deleting_a_paused_chore_pays_nothing`
- `test_deleting_a_member_removes_their_ledger`
- `test_burned_completion_is_ledgered_at_zero`
- `test_deleted_chore_still_shows_in_history`

### CH-19 · Reclaim a burned chore
The person the log says did it can claim it late for half rate.

- `test_reclaim_pays_half_rounded_down`
- `test_reclaim_floors_at_one_point`
- `test_reclaim_halves_after_the_pause_penalty`
- `test_reclaim_is_worse_than_claiming_first`
- `test_reclaim_assigns_the_chore`
- `test_reclaim_upgrades_the_existing_row_rather_than_adding_one`
- `test_reclaim_does_not_double_count_the_chore`
- `test_only_the_person_who_did_it_can_reclaim`
- `test_cannot_reclaim_twice`
- `test_cannot_reclaim_an_owned_chore`
- `test_cannot_reclaim_an_unfinished_chore`
- `test_can_reclaim_predicate_matches_the_rules`
- `test_history_offers_reclaim_to_the_doer`
- `test_history_does_not_offer_reclaim_to_anyone_else`
- `test_reclaim_over_http_awards_half`
- `test_reclaim_by_the_wrong_person_changes_nothing`

### CH-20 · Scenario walkthroughs
Whole-household journeys driven through the views, not the services.

- `test_adding_four_chores_puts_them_all_on_the_board`
- `test_added_chores_appear_on_the_list_page`
- `test_removing_a_chore_takes_it_off_the_board`
- `test_removing_a_finished_chore_keeps_the_points_earned`
- `test_one_session_run_scores_full_points`
- `test_interrupted_run_loses_one_point_per_pause`
- `test_clean_run_beats_an_interrupted_one_on_equal_chores`
- `test_finishing_an_unclaimed_chore_burns_the_points`
- `test_claiming_first_earns_the_points`
- `test_a_full_evening_of_chores`

---

## Definition of done

A ticket is done when its tests pass, `manage.py check` is clean, no migration is
pending, and the feature is reachable in the running app — not just in tests.

## Deliberately not in this backlog

The challenge board, per-person logins, REST API, multi-household, real-time
updates, and any background worker. All are additions to this model, not
rewrites — see the deferred list in the architecture.
