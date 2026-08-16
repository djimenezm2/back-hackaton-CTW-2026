"""
Tests for the seed command's ordering, and for the line between fixtures and reference data.

Loading order is obvious — the catalog first, because everything references it. The order that
actually breaks things is the clearing one, and it is the reverse: a fixture cleared before the
scenario that points at it leaves rows behind, orphaned by the time the run ends and invisible
until somebody counts.
"""

from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from ayudagente.radar.models import Event, Requirement, ResourceType
from ayudagente.radar.seeds import SEEDS
from ayudagente.radar.services import taxonomy


def seed(*args) -> str:
    """Run the command with its output captured."""
    out = StringIO()
    call_command("seed", *args, stdout=out)
    return out.getvalue()


class RegistryTests(TestCase):
    """Nothing a deployment depends on may sit behind a `--clear` flag."""

    def test_the_registry_holds_only_development_fixtures(self):
        self.assertEqual(sorted(SEEDS), ["demo", "pilot"])

    def test_the_resource_catalog_is_not_a_seed(self):
        self.assertNotIn("taxonomy", SEEDS)


class OrderingTests(TestCase):
    def setUp(self):
        taxonomy.load()
        seed("--only", "demo")

    def test_the_scenario_loads_against_the_reference_catalog(self):
        self.assertEqual(ResourceType.objects.count(), len(taxonomy.RESOURCES))
        self.assertTrue(Requirement.objects.exists())

    def test_clearing_a_fixture_leaves_the_catalog_alone(self):
        seed("--only", "demo", "--clear")

        self.assertEqual(Requirement.objects.count(), 0)
        self.assertEqual(Event.objects.count(), 0)
        self.assertEqual(ResourceType.objects.count(), len(taxonomy.RESOURCES))

    def test_flush_ends_with_the_scenario_loaded_and_no_duplicates(self):
        before = Requirement.objects.count()

        seed("--only", "demo", "--flush")

        self.assertEqual(Requirement.objects.count(), before)
        self.assertEqual(ResourceType.objects.count(), len(taxonomy.RESOURCES))

    def test_loading_twice_creates_nothing(self):
        before = Requirement.objects.count()

        seed("--only", "demo")

        self.assertEqual(Requirement.objects.count(), before)


class MissingCatalogTests(TestCase):
    """A scenario that cannot find the catalog says so instead of failing on a KeyError."""

    def test_the_demo_refuses_with_the_command_to_run(self):
        with self.assertRaises(Exception) as caught:
            seed("--only", "demo")

        self.assertIn("load_taxonomy", str(caught.exception))
