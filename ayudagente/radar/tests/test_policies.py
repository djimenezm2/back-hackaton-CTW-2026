"""
Hermetic tests for the rules that must not drift, none of which need a database.

These cover the invariants documented in `docs/data-model.md`: the outreach policy failing
closed, location precision ordering, idempotency key stability, and the resource hierarchy.
"""

import pytest

from ayudagente.radar.choices import ActorKind, ContactKind, LocationPrecision
from ayudagente.radar.models import Actor, ContactPoint, Location, Outreach, ResourceType
from ayudagente.radar.models.actors import (
    MIN_CONFIDENCE_FOR_AUTOMATIC_OUTREACH,
    ORGANIZATION_KINDS,
)


def contact(kind, *, actor_kind, confidence=0.95, reachable=True):
    """Build an unsaved contact point on an unsaved actor, for policy checks only."""
    actor = Actor(kind=actor_kind, is_organization=actor_kind in ORGANIZATION_KINDS)
    return ContactPoint(
        actor=actor,
        kind=kind,
        value="x",
        raw_value="x",
        confidence=confidence,
        reachable=reachable,
    )


class TestAutomaticOutreachPolicy:
    """The single rule that decides whether a human is in the loop."""

    def test_allows_email_to_an_organization(self):
        point = contact(ContactKind.EMAIL, actor_kind=ActorKind.COLLECTION_CENTER)
        assert point.allows_automatic_outreach()

    def test_refuses_email_to_a_person(self):
        point = contact(ContactKind.EMAIL, actor_kind=ActorKind.PERSON)
        assert not point.allows_automatic_outreach()

    @pytest.mark.parametrize(
        "kind",
        [ContactKind.PHONE, ContactKind.WHATSAPP, ContactKind.HANDLE, ContactKind.NEQUI],
    )
    def test_refuses_every_channel_other_than_email(self, kind):
        point = contact(kind, actor_kind=ActorKind.COLLECTION_CENTER)
        assert not point.allows_automatic_outreach()

    def test_refuses_below_the_confidence_floor(self):
        point = contact(
            ContactKind.EMAIL,
            actor_kind=ActorKind.NONPROFIT,
            confidence=MIN_CONFIDENCE_FOR_AUTOMATIC_OUTREACH - 0.01,
        )
        assert not point.allows_automatic_outreach()

    def test_refuses_when_the_channel_is_unreachable(self):
        point = contact(ContactKind.EMAIL, actor_kind=ActorKind.NONPROFIT, reachable=False)
        assert not point.allows_automatic_outreach()

    def test_person_is_never_an_organization(self):
        assert ActorKind.PERSON not in ORGANIZATION_KINDS


class TestLocationPrecision:
    """Precision has to be ordered, or matching cannot enforce a minimum."""

    def test_a_street_address_satisfies_a_municipality_requirement(self):
        location = Location(precision=LocationPrecision.STREET_ADDRESS)
        assert location.is_at_least(LocationPrecision.MUNICIPALITY)

    def test_a_department_does_not_satisfy_a_neighborhood_requirement(self):
        location = Location(precision=LocationPrecision.DEPARTMENT)
        assert not location.is_at_least(LocationPrecision.NEIGHBORHOOD)

    def test_a_precision_always_satisfies_itself(self):
        for value in LocationPrecision.values:
            assert Location(precision=value).is_at_least(value)


class TestIdempotencyKey:
    """Retrying a task must not produce a second message to the same person."""

    def test_same_inputs_produce_the_same_key(self):
        first = Outreach.build_idempotency_key(7, 42, "email")
        second = Outreach.build_idempotency_key(7, 42, "email")
        assert first == second

    def test_channel_changes_the_key(self):
        assert Outreach.build_idempotency_key(7, 42, "email") != Outreach.build_idempotency_key(
            7, 42, "direct_message"
        )

    def test_a_general_message_differs_from_a_match_specific_one(self):
        assert Outreach.build_idempotency_key(7, None, "email") != (
            Outreach.build_idempotency_key(7, 42, "email")
        )


class TestResourceHierarchy:
    """Category fallback depends on walking parents correctly."""

    def test_ancestors_are_returned_nearest_first(self):
        shelter = ResourceType(key="shelter", name="Shelter")
        bedding = ResourceType(key="bedding", name="Bedding", parent=shelter)
        mats = ResourceType(key="mats", name="Sleeping mats", parent=bedding)
        assert mats.ancestors() == [bedding, shelter]

    def test_a_root_resource_has_no_ancestors(self):
        assert ResourceType(key="water", name="Water").ancestors() == []
