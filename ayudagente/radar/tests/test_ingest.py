"""
Tests for turning an extraction into requirements.

Geocoding and identity are stubbed so what gets asserted is the ingest logic itself: what is
refused, what survives the contradiction check, and how contacts accumulate.
"""

from datetime import UTC, datetime

import pytest

from ayudagente.radar.choices import (
    ContactKind,
    Direction,
    ExtractionClass,
    GeocodeSource,
    LocationPrecision,
    Platform,
)
from ayudagente.radar.models import Actor, ContactPoint, Event, Extraction, Location, Observation
from ayudagente.radar.services.geocoding import Geocoder
from ayudagente.radar.services.identity import IdentityResolver
from ayudagente.radar.services.ingest import Ingestor


@pytest.fixture
def event(db):
    return Event.objects.create(
        hazard="earthquake",
        name="Test event",
        occurred_at=datetime(2026, 8, 10, tzinfo=UTC),
        country_code="CO",
        languages=["es"],
        detection_source="manual",
    )


@pytest.fixture
def observation(event):
    return Observation.objects.create(
        event=event,
        platform=Platform.X,
        platform_id="1",
        permalink="https://x.com/a/1",
        posted_at=datetime(2026, 8, 15, tzinfo=UTC),
        text="Alcaldía de Herveo pide ayuda",
        author_handle="voz_tolima",
        raw={},
    )


@pytest.fixture
def somewhere(event):
    return Location.objects.create(
        point="POINT(-75.69 4.81)",
        precision=LocationPrecision.ADMIN_2,
        raw_text="Herveo, Tolima, Colombia",
        text_norm="herveo, tolima, colombia",
        source=GeocodeSource.GOOGLE,
    )


class FixedGeocoder(Geocoder):
    """Resolves everything to one place, so a test asserts ingest rather than Google."""

    def __init__(self, location):
        super().__init__(api_key="unused")
        self.location = location

    def resolve(self, query, event):
        return self.location if query.strip() else None


@pytest.fixture
def ingestor(somewhere):
    return Ingestor(
        geocoder=FixedGeocoder(somewhere),
        resolver=IdentityResolver(use_embeddings=False, use_llm=False),
        resolve_resources=False,
    )


def make_extraction(observation, items, *, classification="need", confidence=0.9, geo="Herveo"):
    payload = {
        "classification": classification,
        "confidence": confidence,
        "language": "es",
        "geocode_query": geo,
        "visual_summary": "",
        "text_image_conflict": False,
        "belongs_to_event": True,
        "items": items,
    }
    return Extraction.objects.create(
        observation=observation,
        model="test",
        prompt_version="test",
        classification=classification,
        confidence=confidence,
        payload=payload,
        geocode_query=geo,
    )


def item(direction, resource_key, *, actor="Alcaldía de Herveo", kind="public_entity", **extra):
    return {
        "direction": direction,
        "resource": resource_key,
        "resource_key": resource_key,
        "quantity": extra.get("quantity"),
        "unit": extra.get("unit", ""),
        "location_text": extra.get("location_text", ""),
        "urgency": extra.get("urgency", "high"),
        "window_text": "",
        "actor": {"name": actor, "kind": kind},
        "contacts": extra.get("contacts", []),
    }


class TestRefusals:
    """Everything refused here would otherwise reach a coordinator as real demand."""

    def test_a_discarded_reading_produces_nothing(self, observation, ingestor):
        extraction = make_extraction(
            observation, [item("needs", "water")], classification=ExtractionClass.DISCARD
        )
        outcome = ingestor.ingest(extraction)
        assert outcome.requirements == []
        assert "discard" in outcome.dropped[0]

    def test_a_low_confidence_reading_produces_nothing(self, observation, ingestor):
        extraction = make_extraction(observation, [item("needs", "water")], confidence=0.2)
        outcome = ingestor.ingest(extraction)
        assert outcome.requirements == []

    def test_an_item_with_nowhere_to_go_is_refused(self, observation, somewhere):
        ingestor = Ingestor(
            geocoder=FixedGeocoder(None),
            resolver=IdentityResolver(use_embeddings=False, use_llm=False),
            resolve_resources=False,
        )
        extraction = make_extraction(observation, [item("needs", "water")], geo="")
        assert ingestor.ingest(extraction).requirements == []


class TestContradictions:
    """An authority asking for help is not also supplying it."""

    def test_an_offer_contradicting_a_need_is_dropped(self, observation, ingestor):
        extraction = make_extraction(
            observation, [item("needs", "shelter"), item("offers", "shelter")]
        )
        outcome = ingestor.ingest(extraction)
        assert len(outcome.requirements) == 1
        assert outcome.requirements[0].direction == Direction.NEEDS
        assert "cannot both need and offer" in outcome.dropped[0]

    def test_a_different_resource_is_not_a_contradiction(self, observation, ingestor):
        extraction = make_extraction(
            observation, [item("offers", "food"), item("needs", "transport")]
        )
        outcome = ingestor.ingest(extraction)
        assert {r.direction for r in outcome.requirements} == {
            Direction.OFFERS,
            Direction.NEEDS,
        }

    def test_two_actors_on_opposite_sides_both_survive(self, observation, ingestor):
        extraction = make_extraction(
            observation,
            [
                item("needs", "water", actor="JAC Barrio Cuba", kind="community"),
                item("offers", "water", actor="Cruz Roja", kind="nonprofit"),
            ],
        )
        assert len(ingestor.ingest(extraction).requirements) == 2


class TestMaterialisation:
    """What lands in the database has to be traceable back to the post."""

    def test_the_observation_is_kept_as_evidence(self, observation, ingestor):
        extraction = make_extraction(observation, [item("needs", "water")])
        requirement = ingestor.ingest(extraction).requirements[0]
        assert observation in requirement.evidence.all()

    def test_an_unknown_resource_key_becomes_a_parentless_leaf(self, observation, ingestor):
        extraction = make_extraction(observation, [item("needs", "drone_batteries")])
        requirement = ingestor.ingest(extraction).requirements[0]
        assert requirement.resource.key == "drone_batteries"
        assert requirement.resource.parent is None

    def test_a_repeated_contact_is_counted_rather_than_duplicated(self, observation, ingestor):
        contact = [{"kind": ContactKind.PHONE, "value": "+573002377012", "network": ""}]
        for _ in range(2):
            extraction = make_extraction(observation, [item("needs", "water", contacts=contact)])
            ingestor.ingest(extraction)
            extraction.delete()

        point = ContactPoint.objects.get(value="+573002377012")
        assert point.times_seen == 2

    def test_repeated_mentions_land_on_one_actor(self, observation, ingestor):
        extraction = make_extraction(observation, [item("needs", "water"), item("needs", "food")])
        ingestor.ingest(extraction)
        assert Actor.objects.filter(canonical_name="Alcaldía de Herveo").count() == 1
