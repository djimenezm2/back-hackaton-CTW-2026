"""
Tests for the seed command's ordering.

Loading order is obvious — the catalog first, because everything references it. The order that
actually breaks things is the clearing one, and it is the reverse: a catalog removed while a
scenario still points at it leaves every referenced row behind, orphaned by the time the run
ends and invisible until somebody counts.
"""

from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from ayudagente.radar.models import Event, Requirement, ResourceType
from ayudagente.radar.seeds import taxonomy


def seed(*args) -> str:
    """Run the command with its output captured."""
    out = StringIO()
    call_command("seed", *args, stdout=out)
    return out.getvalue()


class OrderingTests(TestCase):
    def setUp(self):
        seed("--only", "taxonomy", "demo")

    def test_the_scenario_loads_against_the_shared_catalog(self):
        self.assertEqual(ResourceType.objects.count(), len(taxonomy.RESOURCES))
        self.assertTrue(Requirement.objects.exists())

    def test_clearing_leaves_no_orphan_catalog_rows(self):
        seed("--only", "taxonomy", "demo", "--clear")

        self.assertEqual(Requirement.objects.count(), 0)
        self.assertEqual(Event.objects.count(), 0)
        self.assertEqual(ResourceType.objects.count(), 0)

    def test_flush_ends_with_the_scenario_loaded_and_no_duplicates(self):
        before = Requirement.objects.count()

        seed("--only", "taxonomy", "demo", "--flush")

        self.assertEqual(Requirement.objects.count(), before)
        self.assertEqual(ResourceType.objects.count(), len(ResourceType.objects.distinct()))

    def test_loading_twice_creates_nothing(self):
        before = Requirement.objects.count()

        seed("--only", "taxonomy", "demo")

        self.assertEqual(Requirement.objects.count(), before)
