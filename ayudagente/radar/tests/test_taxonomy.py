"""
Tests for the resource catalog seed.

Creating rows is the easy half. The half worth testing is what the seed does to a database
that already has the wrong ones — the Spanish-keyed duplicates and the nameless leaves the
pipeline invents — because that is the state every existing machine is actually in.
"""

from django.test import TestCase

from ayudagente.radar.models import Requirement, ResourceType
from ayudagente.radar.seeds import taxonomy
from ayudagente.radar.tests.factories import (
    PEREIRA,
    make_actor,
    make_event,
    make_location,
    make_requirement,
)


def load() -> dict:
    """Run the seed with its output discarded."""
    return taxonomy.load(lambda _: None)


class LoadTests(TestCase):
    def test_it_creates_the_whole_catalog_and_wires_the_hierarchy(self):
        counts = load()

        self.assertEqual(counts["resource_types"], len(taxonomy.RESOURCES))
        parent = ResourceType.objects.get(key="pet_food").parent
        assert parent is not None
        self.assertEqual(parent.key, "food")

    def test_a_second_run_creates_nothing(self):
        load()

        self.assertEqual(load()["resource_types"], 0)
        self.assertEqual(ResourceType.objects.count(), len(taxonomy.RESOURCES))


class AdoptionTests(TestCase):
    """A key the pipeline invented gets its Spanish name once the taxonomy declares it."""

    def test_a_leaf_named_after_its_key_is_adopted(self):
        ResourceType.objects.create(key="support", name="support")

        counts = load()

        adopted = ResourceType.objects.get(key="support")
        assert adopted.parent is not None
        self.assertEqual(counts["adopted"], 1)
        self.assertEqual(adopted.name, "Apoyo general")
        self.assertEqual(adopted.parent.key, "volunteers")
        self.assertEqual(adopted.default_unit, "personas")

    def test_a_row_somebody_named_is_left_alone(self):
        ResourceType.objects.create(key="water", name="Agua potable del acueducto")

        counts = load()

        self.assertEqual(counts["adopted"], 0)
        self.assertEqual(ResourceType.objects.get(key="water").name, "Agua potable del acueducto")

    def test_adoption_does_not_repeat_on_a_second_run(self):
        ResourceType.objects.create(key="support", name="support")
        load()

        self.assertEqual(load()["adopted"], 0)


class LegacyKeyTests(TestCase):
    """The Spanish-keyed duplicates left behind by the data migration this seed replaced."""

    def setUp(self):
        self.event = make_event()
        self.actor = make_actor(self.event, "Barrio Cuba")

    def test_a_duplicate_with_no_requirements_is_removed(self):
        ResourceType.objects.create(key="agua", name="Agua")

        counts = load()

        self.assertEqual(counts["retired"], 1)
        self.assertFalse(ResourceType.objects.filter(key="agua").exists())

    def test_requirements_are_repointed_rather_than_orphaned(self):
        legacy = ResourceType.objects.create(key="transporte", name="Transporte")
        requirement = make_requirement(
            self.event, self.actor, legacy, make_location(PEREIRA, "cuba")
        )

        load()

        requirement.refresh_from_db()
        self.assertEqual(requirement.resource.key, "transport")
        self.assertFalse(ResourceType.objects.filter(key="transporte").exists())

    def test_a_child_of_a_duplicate_is_repointed_too(self):
        legacy = ResourceType.objects.create(key="alimentos", name="Alimentos")
        orphan = ResourceType.objects.create(key="enlatados", name="Enlatados", parent=legacy)

        load()

        orphan.refresh_from_db()
        assert orphan.parent is not None
        self.assertEqual(orphan.parent.key, "food")

    def test_nothing_is_retired_when_the_catalog_is_already_clean(self):
        load()

        self.assertEqual(load()["retired"], 0)

    def test_the_catalog_ends_with_exactly_the_declared_types(self):
        for legacy_key in taxonomy.LEGACY_KEYS:
            ResourceType.objects.create(key=legacy_key, name=legacy_key)

        load()

        self.assertEqual(
            sorted(ResourceType.objects.values_list("key", flat=True)),
            sorted(key for key, *_ in taxonomy.RESOURCES),
        )

    def test_no_requirement_is_lost_to_the_merge(self):
        for legacy_key in ("agua", "alimentos", "voluntarios"):
            legacy = ResourceType.objects.create(key=legacy_key, name=legacy_key)
            make_requirement(
                self.event, self.actor, legacy, make_location(PEREIRA, f"sitio {legacy_key}")
            )

        load()

        self.assertEqual(Requirement.objects.count(), 3)
        self.assertEqual(
            sorted(Requirement.objects.values_list("resource__key", flat=True)),
            ["food", "volunteers", "water"],
        )
