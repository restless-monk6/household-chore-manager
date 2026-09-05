"""End-to-end walkthroughs: add several chores, remove one, work them, score them.

These drive the real views over HTTP rather than calling services directly, so
they cover the URLs, the session actor, the forms and the templates together.
"""

from django.test import TestCase
from django.urls import reverse

from chores import services
from chores.models import Chore, ChoreEvent, EventKind, Member, PointsAward, Status
from chores.views import ACTOR_SESSION_KEY


class HouseholdWalkthroughTests(TestCase):
    """One household, four chores, two ways of working through them."""

    def setUp(self):
        self.alex = Member.objects.create(name="Alex")
        self.sam = Member.objects.create(name="Sam")

    # --- helpers -----------------------------------------------------------

    def acting_as(self, member):
        session = self.client.session
        session[ACTOR_SESSION_KEY] = member.pk
        session.save()

    def add_chore(self, name, category, points, owner=None):
        response = self.client.post(
            reverse("chore_new"),
            {
                "name": name,
                "category": category,
                "points": points,
                "recurrence": "none",
                "notes": "",
                "assigned_to": owner.pk if owner else "",
            },
        )
        self.assertRedirects(response, reverse("dashboard"))
        return Chore.objects.get(name=name)

    def act(self, chore, action):
        return self.client.post(reverse("chore_action", args=[chore.pk, action]))

    def add_four(self):
        return [
            self.add_chore("Mow the lawn", "outdoor", 5, self.alex),
            self.add_chore("Clean the toilet", "bathroom", 3, self.sam),
            self.add_chore("Iron a batch", "laundry", 3, self.alex),
            self.add_chore("Feed the pet", "pets", 1),  # nobody: shared pool
        ]

    # --- adding ------------------------------------------------------------

    def test_adding_four_chores_puts_them_all_on_the_board(self):
        self.add_four()
        self.assertEqual(Chore.objects.count(), 4)
        self.assertEqual(Chore.objects.filter(status=Status.PENDING).count(), 4)

        # Nothing is scored merely by existing.
        self.assertEqual(services.member_points(self.alex), 0)
        self.assertEqual(services.member_points(self.sam), 0)

        buckets = services.dashboard()
        self.assertEqual(buckets["pool"].count(), 1)
        self.assertEqual(
            buckets["pool"].get().name, "Feed the pet", "unowned chore joins the pool"
        )

    def test_added_chores_appear_on_the_list_page(self):
        self.add_four()
        page = self.client.get(reverse("chore_list"))
        for name in ["Mow the lawn", "Clean the toilet", "Iron a batch", "Feed the pet"]:
            self.assertContains(page, name)

    # --- removing ----------------------------------------------------------

    def test_removing_a_chore_takes_it_off_the_board(self):
        _, _, ironing, _ = self.add_four()

        confirm = self.client.get(reverse("chore_delete", args=[ironing.pk]))
        self.assertContains(confirm, "Iron a batch")

        response = self.client.post(reverse("chore_delete", args=[ironing.pk]))
        self.assertRedirects(response, reverse("dashboard"))

        self.assertEqual(Chore.objects.count(), 3)
        self.assertFalse(Chore.objects.filter(name="Iron a batch").exists())
        self.assertNotContains(self.client.get(reverse("chore_list")), "Iron a batch")

    def test_removing_a_started_chore_removes_its_events_too(self):
        _, _, ironing, _ = self.add_four()
        self.acting_as(self.alex)
        self.act(ironing, "start")
        self.assertEqual(ChoreEvent.objects.filter(chore=ironing).count(), 1)

        self.client.post(reverse("chore_delete", args=[ironing.pk]))
        self.assertEqual(ChoreEvent.objects.count(), 0, "events cascade with the chore")

    def test_removing_a_finished_chore_keeps_the_points_earned(self):
        mowing, _, _, _ = self.add_four()
        self.acting_as(self.alex)
        self.act(mowing, "start")
        self.act(mowing, "finish")
        self.assertEqual(services.member_points(self.alex), 5)

        self.client.post(reverse("chore_delete", args=[mowing.pk]))

        self.assertFalse(Chore.objects.filter(name="Mow the lawn").exists())
        self.assertEqual(
            services.member_points(self.alex), 5, "earned points are history"
        )
        award = PointsAward.objects.get(member=self.alex)
        self.assertIsNone(award.chore, "the ledger row outlives the chore")
        self.assertEqual(award.chore_name, "Mow the lawn", "name is snapshotted")

    # --- scenario 1: start to finish in one session ------------------------

    def test_one_session_run_scores_full_points(self):
        mowing, _, _, _ = self.add_four()
        self.acting_as(self.alex)

        self.act(mowing, "start")
        mowing.refresh_from_db()
        self.assertEqual(mowing.status, Status.IN_PROGRESS)

        self.act(mowing, "finish")
        mowing.refresh_from_db()

        self.assertEqual(mowing.status, Status.COMPLETED)
        self.assertEqual(mowing.pause_count, 0)
        self.assertEqual(mowing.points_awarded, 5, "5 points, no pauses, full value")
        self.assertEqual(mowing.completed_by, self.alex)
        self.assertIsNotNone(mowing.completed_at)
        self.assertEqual(
            list(mowing.events.values_list("kind", flat=True)),
            [EventKind.STARTED, EventKind.FINISHED],
        )
        self.assertEqual(services.member_points(self.alex), 5)

    # --- scenario 2: paused, picked up later --------------------------------

    def test_interrupted_run_loses_one_point_per_pause(self):
        _, toilet, _, _ = self.add_four()
        self.acting_as(self.sam)

        self.act(toilet, "start")
        self.act(toilet, "pause")
        toilet.refresh_from_db()
        self.assertEqual(toilet.status, Status.PAUSED)
        self.assertIsNone(toilet.points_awarded, "nothing scored until it is finished")

        # Sam wanders off and comes back later — a fresh browser session.
        self.client = self.client_class()
        self.acting_as(self.sam)

        self.act(toilet, "resume")
        toilet.refresh_from_db()
        self.assertEqual(toilet.status, Status.IN_PROGRESS)

        self.act(toilet, "finish")
        toilet.refresh_from_db()

        self.assertEqual(toilet.status, Status.COMPLETED)
        self.assertEqual(toilet.pause_count, 1)
        self.assertEqual(toilet.points_awarded, 2, "3 points less one pause")
        self.assertEqual(toilet.completed_by, self.sam)
        self.assertEqual(
            list(toilet.events.values_list("kind", flat=True)),
            [
                EventKind.STARTED,
                EventKind.PAUSED,
                EventKind.RESUMED,
                EventKind.FINISHED,
            ],
        )
        self.assertEqual(services.member_points(self.sam), 2)

    # --- the two scenarios side by side ------------------------------------

    def test_clean_run_beats_an_interrupted_one_on_equal_chores(self):
        clean = self.add_chore("Cook dinner", "kitchen", 3, self.alex)
        messy = self.add_chore("Mop the floors", "living", 3, self.sam)

        self.acting_as(self.alex)
        self.act(clean, "start")
        self.act(clean, "finish")

        self.acting_as(self.sam)
        self.act(messy, "start")
        self.act(messy, "pause")
        self.act(messy, "resume")
        self.act(messy, "pause")
        self.act(messy, "resume")
        self.act(messy, "finish")

        clean.refresh_from_db()
        messy.refresh_from_db()
        self.assertEqual(clean.points_awarded, 3)
        self.assertEqual(messy.points_awarded, 1, "same chore, two pauses, 3 - 2")
        self.assertEqual(
            [r["member"] for r in services.leaderboard()], [self.alex, self.sam]
        )

    # --- the unclaimed case -------------------------------------------------

    def test_finishing_an_unclaimed_chore_burns_the_points(self):
        _, _, _, pet = self.add_four()
        self.acting_as(self.alex)

        self.act(pet, "start")
        self.act(pet, "finish")
        pet.refresh_from_db()

        self.assertEqual(pet.status, Status.COMPLETED)
        self.assertEqual(pet.points_awarded, 0)
        self.assertEqual(pet.completed_by, self.alex, "still recorded in history")
        self.assertEqual(services.member_points(self.alex), 0)

    def test_claiming_first_earns_the_points(self):
        _, _, _, pet = self.add_four()
        self.acting_as(self.alex)

        self.act(pet, "claim")
        pet.refresh_from_db()
        self.assertEqual(pet.assigned_to, self.alex)

        self.act(pet, "start")
        self.act(pet, "finish")
        pet.refresh_from_db()

        self.assertEqual(pet.points_awarded, 1)
        self.assertEqual(services.member_points(self.alex), 1)


class FullHouseholdLedgerTests(TestCase):
    """The whole thing at once: add four, delete one, work the rest, check totals."""

    def test_a_full_evening_of_chores(self):
        alex = Member.objects.create(name="Alex")
        sam = Member.objects.create(name="Sam")

        mowing = Chore.objects.create(name="Mow the lawn", points=5, assigned_to=alex)
        toilet = Chore.objects.create(name="Clean the toilet", points=3, assigned_to=sam)
        ironing = Chore.objects.create(name="Iron a batch", points=3, assigned_to=alex)
        pet = Chore.objects.create(name="Feed the pet", points=1)

        # Ironing is cancelled before anyone touches it.
        ironing.delete()

        # Alex: clean run on a 5-pointer.
        services.transition(mowing, "start", actor=alex)
        services.transition(mowing, "finish", actor=alex)

        # Sam: starts, breaks off, resumes later, finishes.
        services.transition(toilet, "start", actor=sam)
        services.transition(toilet, "pause", actor=sam)
        services.transition(toilet, "resume", actor=sam)
        services.transition(toilet, "finish", actor=sam)

        # Nobody claimed the pet, and Sam feeds it anyway.
        services.transition(pet, "start", actor=sam)
        services.transition(pet, "finish", actor=sam)

        self.assertEqual(Chore.objects.count(), 3)
        self.assertEqual(mowing.points_awarded, 5)
        self.assertEqual(toilet.points_awarded, 2)
        self.assertEqual(pet.points_awarded, 0)

        self.assertEqual(services.member_points(alex), 5)
        self.assertEqual(services.member_points(sam), 2)
        self.assertEqual(PointsAward.objects.count(), 3, "every completion is ledgered")
        self.assertEqual(services.clean_run_rate(alex), 100)
        self.assertEqual(services.clean_run_rate(sam), 50, "one of Sam's two paused")

        board = services.leaderboard()
        self.assertEqual([(r["member"].name, r["points"]) for r in board],
                         [("Alex", 5), ("Sam", 2)])
