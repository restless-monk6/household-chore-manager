"""Load the standard chore catalog so a new household starts with a real board."""

from django.core.management.base import BaseCommand

from chores.catalog import CATALOG
from chores.models import Chore, Status


class Command(BaseCommand):
    help = "Create the standard household chores (idempotent)."

    def handle(self, *args, **options):
        created = 0
        for category, name, points in CATALOG:
            # Skip anything already waiting on the board under this name, however
            # many of them there are: re-running must not duplicate the catalog.
            if Chore.objects.filter(name=name, status=Status.PENDING).exists():
                continue
            Chore.objects.create(name=name, category=category, points=points)
            created += 1
        self.stdout.write(
            self.style.SUCCESS(
                f"Catalog loaded: {created} new, {len(CATALOG) - created} already present."
            )
        )
