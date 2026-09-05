from datetime import timedelta

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from chores import services
from chores.models import Chore, Member, PointsAward, Status
from chores.views import ACTOR_SESSION_KEY


class SmokeTests(TestCase):
    def test_dashboard_url_resolves(self):
        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Household Chores")

    def test_every_page_renders(self):
        member = Member.objects.create(name="Alex")
        Chore.objects.create(name="Make the bed", points=1, assigned_to=member)
        for url in [
            reverse("dashboard"),
            reverse("chore_list"),
            reverse("chore_new"),
            reverse("history"),
            reverse("member_detail", args=[member.pk]),
        ]:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_member_page_404s_for_unknown_member(self):
        self.assertEqual(
            self.client.get(reverse("member_detail", args=[999])).status_code, 404
        )


class ChoreFormTests(TestCase):
    def test_create_valid_redirects_and_persists(self):
        response = self.client.post(
            reverse("chore_new"),
            {"name": "Walk the dog", "category": "pets", "recurrence": "none",
             "points": 2, "notes": ""},
        )
        self.assertRedirects(response, reverse("dashboard"))
        self.assertTrue(Chore.objects.filter(name="Walk the dog").exists())

    def test_create_invalid_rerenders_with_errors(self):
        response = self.client.post(
            reverse("chore_new"),
            {"name": "", "category": "pets", "recurrence": "none", "points": 2},
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Chore.objects.exists())

    def test_create_prefills_points_from_catalog(self):
        self.client.post(
            reverse("chore_new"),
            {"name": "Mow the lawn", "category": "outdoor", "recurrence": "none",
             "points": "", "notes": ""},
        )
        self.assertEqual(Chore.objects.get(name="Mow the lawn").points, 5)

    def test_submitted_points_beat_the_catalog(self):
        self.client.post(
            reverse("chore_new"),
            {"name": "Mow the lawn", "category": "outdoor", "recurrence": "none",
             "points": 1, "notes": ""},
        )
        self.assertEqual(Chore.objects.get(name="Mow the lawn").points, 1)

    def test_editing_another_field_keeps_the_chosen_price(self):
        chore = Chore.objects.create(name="Mow the lawn", category="outdoor", points=1)
        self.client.post(
            reverse("chore_edit", args=[chore.pk]),
            {"name": "Mow the lawn", "category": "outdoor", "recurrence": "none",
             "points": 1, "notes": "front garden only"},
        )
        chore.refresh_from_db()
        self.assertEqual(chore.points, 1, "the catalog does not re-price it")
        self.assertEqual(chore.notes, "front garden only")

    def test_blank_points_on_an_unlisted_chore_falls_back_to_one(self):
        self.client.post(
            reverse("chore_new"),
            {"name": "Polish the doorknobs", "category": "living",
             "recurrence": "none", "points": "", "notes": ""},
        )
        self.assertEqual(Chore.objects.get().points, 1)

    def test_empty_post_reports_errors_instead_of_doing_nothing(self):
        response = self.client.post(reverse("chore_new"), {})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["form"].errors)
        self.assertFalse(Chore.objects.exists())

    def test_edit_updates_without_creating_a_row(self):
        chore = Chore.objects.create(name="Dust surfaces", points=2)
        self.client.post(
            reverse("chore_edit", args=[chore.pk]),
            {"name": "Dust everything", "category": "living", "recurrence": "none",
             "points": 2, "notes": ""},
        )
        self.assertEqual(Chore.objects.count(), 1)
        self.assertEqual(Chore.objects.get().name, "Dust everything")


class ActionViewTests(TestCase):
    def setUp(self):
        self.member = Member.objects.create(name="Alex")
        self.chore = Chore.objects.create(
            name="Mow the lawn", points=5, assigned_to=self.member
        )
        session = self.client.session
        session[ACTOR_SESSION_KEY] = self.member.pk
        session.save()

    def test_get_is_rejected(self):
        response = self.client.get(
            reverse("chore_action", args=[self.chore.pk, "start"])
        )
        self.assertEqual(response.status_code, 405)
        self.chore.refresh_from_db()
        self.assertEqual(self.chore.status, Status.PENDING)

    def test_post_starts_the_chore(self):
        self.client.post(reverse("chore_action", args=[self.chore.pk, "start"]))
        self.chore.refresh_from_db()
        self.assertEqual(self.chore.status, Status.IN_PROGRESS)

    def test_illegal_transition_redirects_without_500(self):
        response = self.client.post(
            reverse("chore_action", args=[self.chore.pk, "pause"])
        )
        self.assertEqual(response.status_code, 302)
        self.chore.refresh_from_db()
        self.assertEqual(self.chore.status, Status.PENDING)

    def test_unknown_action_redirects_without_500(self):
        response = self.client.post(
            reverse("chore_action", args=[self.chore.pk, "explode"])
        )
        self.assertEqual(response.status_code, 302)

    def test_claim_assigns_to_current_member(self):
        pool_chore = Chore.objects.create(name="Feed the pet", points=1)
        self.client.post(reverse("chore_action", args=[pool_chore.pk, "claim"]))
        pool_chore.refresh_from_db()
        self.assertEqual(pool_chore.assigned_to, self.member)


class DashboardBucketTests(TestCase):
    def test_buckets_split_overdue_and_pool(self):
        member = Member.objects.create(name="Alex")
        now = timezone.now()
        Chore.objects.create(
            name="Clean the toilet", points=3, assigned_to=member,
            due_at=now - timedelta(hours=2),
        )
        Chore.objects.create(name="Feed the pet", points=1, due_at=now + timedelta(hours=2))
        buckets = services.dashboard()
        self.assertEqual(buckets["overdue"].count(), 1)
        self.assertEqual(buckets["pool"].count(), 1)

    def test_completed_never_appears_in_overdue(self):
        member = Member.objects.create(name="Alex")
        chore = Chore.objects.create(
            name="Clean the toilet", points=3, assigned_to=member,
            due_at=timezone.now() - timedelta(hours=2),
        )
        services.transition(chore, "start", actor=member)
        services.transition(chore, "finish", actor=member)
        self.assertEqual(services.dashboard()["overdue"].count(), 0)

    def test_list_filters_by_member(self):
        alex = Member.objects.create(name="Alex")
        sam = Member.objects.create(name="Sam")
        Chore.objects.create(name="Make the bed", points=1, assigned_to=alex)
        Chore.objects.create(name="Walk the dog", points=2, assigned_to=sam)
        response = self.client.get(reverse("chore_list"), {"member": alex.pk})
        self.assertContains(response, "Make the bed")
        self.assertNotContains(response, "Walk the dog")


class RedirectSafetyTests(TestCase):
    """`next` is user-supplied, so it must not become an open redirect."""

    def setUp(self):
        self.member = Member.objects.create(name="Alex")
        self.chore = Chore.objects.create(
            name="Make the bed", points=1, assigned_to=self.member
        )

    def test_external_next_is_ignored_on_action(self):
        response = self.client.post(
            reverse("chore_action", args=[self.chore.pk, "start"]),
            {"next": "http://evil.example.com/steal"},
        )
        self.assertRedirects(response, reverse("dashboard"))

    def test_external_next_is_ignored_on_whoami(self):
        response = self.client.post(
            reverse("set_actor"),
            {"member": self.member.pk, "next": "http://evil.example.com/steal"},
        )
        self.assertRedirects(response, reverse("dashboard"))

    def test_local_next_is_honoured(self):
        response = self.client.post(
            reverse("chore_action", args=[self.chore.pk, "start"]),
            {"next": reverse("chore_list")},
        )
        self.assertRedirects(response, reverse("chore_list"))

    def test_next_that_is_not_a_path_falls_back_to_the_dashboard(self):
        # "oops" passes the host check, and redirect() would try to reverse it.
        response = self.client.post(
            reverse("chore_action", args=[self.chore.pk, "start"]), {"next": "oops"}
        )
        self.assertRedirects(response, reverse("dashboard"))

    def test_non_numeric_member_clears_actor(self):
        response = self.client.post(reverse("set_actor"), {"member": "bogus"})
        self.assertRedirects(response, reverse("dashboard"))
        self.assertIsNone(self.client.session.get(ACTOR_SESSION_KEY))


class ClaimGuardViewTests(TestCase):
    """Claiming is a way into the pool, never a way to take someone's work."""

    def setUp(self):
        self.alex = Member.objects.create(name="Alex")
        self.sam = Member.objects.create(name="Sam")
        session = self.client.session
        session[ACTOR_SESSION_KEY] = self.sam.pk
        session.save()

    def test_claiming_a_chore_someone_owns_is_refused(self):
        chore = Chore.objects.create(
            name="Mow the lawn", points=5, assigned_to=self.alex
        )
        response = self.client.post(reverse("chore_action", args=[chore.pk, "claim"]))
        self.assertEqual(response.status_code, 302)
        chore.refresh_from_db()
        self.assertEqual(chore.assigned_to, self.alex, "not Sam's to take")

    def test_claiming_a_burned_chore_is_refused(self):
        chore = Chore.objects.create(name="Feed the pet", points=1)
        services.transition(chore, "start", actor=self.alex)
        services.transition(chore, "finish", actor=self.alex)

        response = self.client.post(reverse("chore_action", args=[chore.pk, "claim"]))
        self.assertEqual(response.status_code, 302)
        chore.refresh_from_db()
        self.assertIsNone(chore.assigned_to)
        self.assertTrue(
            services.can_reclaim(chore, self.alex), "Alex can still reclaim it"
        )


class UnattributableCompletionTests(TestCase):
    """A completion nobody can be credited for would never reach the ledger."""

    def test_starting_an_unowned_chore_with_no_actor_is_refused(self):
        chore = Chore.objects.create(name="Feed the pet", points=1)
        response = self.client.post(reverse("chore_action", args=[chore.pk, "start"]))
        self.assertEqual(response.status_code, 302)
        chore.refresh_from_db()
        self.assertEqual(chore.status, Status.PENDING)
        self.assertEqual(chore.events.count(), 0)

    def test_finishing_an_unowned_chore_with_no_actor_is_refused(self):
        member = Member.objects.create(name="Alex")
        chore = Chore.objects.create(name="Feed the pet", points=1)
        services.transition(chore, "start", actor=member)

        self.client.post(reverse("chore_action", args=[chore.pk, "finish"]))
        chore.refresh_from_db()
        self.assertEqual(chore.status, Status.IN_PROGRESS)
        self.assertEqual(PointsAward.objects.count(), 0)

    def test_an_owned_chore_still_works_with_no_actor(self):
        member = Member.objects.create(name="Alex")
        chore = Chore.objects.create(name="Make the bed", points=1, assigned_to=member)
        self.client.post(reverse("chore_action", args=[chore.pk, "start"]))
        self.client.post(reverse("chore_action", args=[chore.pk, "finish"]))
        chore.refresh_from_db()
        self.assertEqual(chore.status, Status.COMPLETED)
        self.assertEqual(PointsAward.objects.get().member, member, "credit the owner")


class CompletedChoreEditTests(TestCase):
    """Setting an owner after the fact would void the doer's reclaim."""

    def setUp(self):
        self.alex = Member.objects.create(name="Alex")
        self.sam = Member.objects.create(name="Sam")
        self.chore = Chore.objects.create(name="Mow the lawn", points=5)
        services.transition(self.chore, "start", actor=self.alex)
        services.transition(self.chore, "finish", actor=self.alex)

    def test_editing_cannot_assign_a_completed_chore(self):
        self.client.post(
            reverse("chore_edit", args=[self.chore.pk]),
            {"name": "Mow the lawn", "category": "outdoor", "recurrence": "none",
             "points": 5, "notes": "", "assigned_to": self.sam.pk},
        )
        self.chore.refresh_from_db()
        self.assertIsNone(self.chore.assigned_to)
        self.assertTrue(services.can_reclaim(self.chore, self.alex))

    def test_editing_an_open_chore_still_assigns_it(self):
        chore = Chore.objects.create(name="Iron a batch", points=3)
        self.client.post(
            reverse("chore_edit", args=[chore.pk]),
            {"name": "Iron a batch", "category": "laundry", "recurrence": "none",
             "points": 3, "notes": "", "assigned_to": self.sam.pk},
        )
        chore.refresh_from_db()
        self.assertEqual(chore.assigned_to, self.sam)


class DashboardBucketOverlapTests(TestCase):
    """Every chore renders once: overdue, then today, in progress, pool, undated."""

    def setUp(self):
        self.member = Member.objects.create(name="Alex")
        self.past = timezone.now() - timedelta(hours=2)

    def _rendered(self, response):
        names = []
        for bucket in ["overdue", "today", "in_progress", "pool", "undated"]:
            names += [chore.name for chore in response.context[bucket]]
        return names

    def test_a_paused_overdue_chore_shows_only_in_overdue(self):
        chore = Chore.objects.create(
            name="Iron a batch", points=3, assigned_to=self.member, due_at=self.past
        )
        services.transition(chore, "start", actor=self.member)
        services.transition(chore, "pause", actor=self.member)

        response = self.client.get(reverse("dashboard"))
        self.assertEqual(self._rendered(response), ["Iron a batch"])
        self.assertEqual(len(response.context["overdue"]), 1)

    def test_an_unowned_overdue_chore_shows_only_in_overdue(self):
        Chore.objects.create(name="Feed the pet", points=1, due_at=self.past)
        response = self.client.get(reverse("dashboard"))
        self.assertEqual(self._rendered(response), ["Feed the pet"])
        self.assertEqual(len(response.context["pool"]), 0)

    def test_an_unowned_undated_chore_still_reaches_the_pool(self):
        Chore.objects.create(name="Feed the pet", points=1)
        response = self.client.get(reverse("dashboard"))
        self.assertEqual([c.name for c in response.context["pool"]], ["Feed the pet"])


class QueryCountTests(TestCase):
    """The pages must not fire another query for every row they render."""

    def setUp(self):
        self.member = Member.objects.create(name="Alex")

    def _paused_chores(self, count):
        for index in range(count):
            chore = Chore.objects.create(
                name=f"Chore {index}", points=2, assigned_to=self.member
            )
            services.transition(chore, "start", actor=self.member)
            services.transition(chore, "pause", actor=self.member)

    def _finished_chores(self, count):
        for index in range(count):
            chore = Chore.objects.create(
                name=f"Done {index}", points=2, assigned_to=self.member
            )
            services.transition(chore, "start", actor=self.member)
            services.transition(chore, "finish", actor=self.member)

    def _queries(self, url):
        with CaptureQueriesContext(connection) as captured:
            self.client.get(url)
        return len(captured)

    def assertFlat(self, url, add_rows):
        add_rows(1)
        few = self._queries(url)
        add_rows(6)
        self.assertEqual(self._queries(url), few, "a query per row crept back in")

    def test_dashboard_query_count_is_flat(self):
        self.assertFlat(reverse("dashboard"), self._paused_chores)

    def test_chore_list_query_count_is_flat(self):
        self.assertFlat(reverse("chore_list"), self._paused_chores)

    def test_member_page_query_count_is_flat(self):
        url = reverse("member_detail", args=[self.member.pk])
        self.assertFlat(url, self._finished_chores)

    def test_history_query_count_is_flat(self):
        self.assertFlat(reverse("history"), self._finished_chores)

    def test_leaderboard_query_count_does_not_grow_with_the_household(self):
        self._finished_chores(2)
        with CaptureQueriesContext(connection) as small:
            services.leaderboard()

        for name in ["Sam", "Rosie", "Theo", "Jo", "Kim"]:
            Member.objects.create(name=name)
        with CaptureQueriesContext(connection) as large:
            services.leaderboard()
        self.assertEqual(len(large), len(small))
