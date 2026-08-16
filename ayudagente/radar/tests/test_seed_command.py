"""
Tests for the seed command, and for the line between fixtures and reference data.

What the command guarantees is that loading twice adds nothing and that clearing takes the
fixture without touching the catalog underneath it. The catalog is the part worth asserting:
it is loaded by its own command because a deployment depends on it, so a `--clear` run that
reached it would take production data out with a development fixture.
"""

from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from ayudagente.radar.models import Event, Observation, ResourceType
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
        self.assertEqual(sorted(SEEDS), ["pilot"])

    def test_the_resource_catalog_is_not_a_seed(self):
        self.assertNotIn("taxonomy", SEEDS)


class PilotTests(TestCase):
    def setUp(self):
        taxonomy.load()
        seed("--only", "pilot")

    def test_the_corpus_loads_against_the_reference_catalog(self):
        self.assertEqual(ResourceType.objects.count(), len(taxonomy.RESOURCES))
        self.assertTrue(Observation.objects.exists())

    def test_clearing_a_fixture_leaves_the_catalog_alone(self):
        seed("--only", "pilot", "--clear")

        self.assertEqual(Observation.objects.count(), 0)
        self.assertEqual(Event.objects.count(), 0)
        self.assertEqual(ResourceType.objects.count(), len(taxonomy.RESOURCES))

    def test_flush_ends_with_the_corpus_loaded_and_no_duplicates(self):
        before = Observation.objects.count()

        seed("--only", "pilot", "--flush")

        self.assertEqual(Observation.objects.count(), before)
        self.assertEqual(ResourceType.objects.count(), len(taxonomy.RESOURCES))

    def test_loading_twice_creates_nothing(self):
        before = Observation.objects.count()

        seed("--only", "pilot")

        self.assertEqual(Observation.objects.count(), before)
