"""
Turning what the model read into what we believe about the world.

This is where interpretation becomes state: each extracted item gets its actor resolved, its
place geocoded, its contacts recorded, and lands as a `Requirement` backed by the observation
it came from. It is the last step that can still refuse — once a requirement exists, matching
will act on it.
"""

from dataclasses import dataclass, field

from django.db import transaction
from django.utils import timezone

from ayudagente.radar.choices import Direction, ExtractionClass, RequirementStatus, Urgency
from ayudagente.radar.models import (
    ContactPoint,
    Extraction,
    Location,
    Observation,
    Requirement,
    ResourceType,
)
from ayudagente.radar.schemas import ExtractedContact, ExtractedItem, ExtractionResult
from ayudagente.radar.services.geocoding import Geocoder
from ayudagente.radar.services.identity import IdentityResolver
from ayudagente.radar.services.text import normalize

# Nothing below this is worth putting in front of a person during an emergency.
MIN_ITEM_CONFIDENCE = 0.4


@dataclass
class Ingested:
    """
    What one extraction produced.

    Attributes:
        requirements (list[Requirement]): Rows created, one per surviving item.
        dropped (list[str]): Why each rejected item was rejected, kept so a silent loss can
            be told apart from a post that genuinely said nothing.
    """

    requirements: list[Requirement] = field(default_factory=list)
    dropped: list[str] = field(default_factory=list)


class Ingestor:
    """
    Builds actors, locations, contacts and requirements from one extraction.

    Note:
        The contradiction check lives here rather than in extraction, because spotting that
        one actor both needs and offers the same resource requires the actor to be resolved
        first — inside a single reading the names have usually drifted. Measured across model
        tiers: a post where an authority asks for help is repeatedly read as also offering it.

        When it fires, the need wins. An authority coordinating a response is not supplying
        the thing it just asked for, and a phantom offer is worse than a missing one: it makes
        a shortage look covered.
    """

    def __init__(
        self,
        geocoder: Geocoder | None = None,
        resolver: IdentityResolver | None = None,
        min_confidence: float = MIN_ITEM_CONFIDENCE,
    ):
        self.geocoder = geocoder or Geocoder()
        self.resolver = resolver or IdentityResolver()
        self.min_confidence = min_confidence

    @transaction.atomic
    def ingest(self, extraction: Extraction) -> Ingested:
        """
        Materialise one extraction, skipping what should not reach a person.

        Args:
            extraction (Extraction): A stored reading.

        Returns:
            Ingested: The requirements created, and a reason for everything dropped.
        """
        result = ExtractionResult.model_validate(extraction.payload)
        outcome = Ingested()

        if extraction.classification == ExtractionClass.DISCARD:
            outcome.dropped.append("classified as discard")
            return outcome
        if extraction.confidence < self.min_confidence:
            outcome.dropped.append(f"confidence {extraction.confidence:.2f} below floor")
            return outcome

        observation = extraction.observation
        location = self.geocoder.resolve(extraction.geocode_query, observation.event)

        for item in self._without_contradictions(result.items, outcome):
            requirement = self._build(item, observation, location, extraction)
            if requirement is not None:
                outcome.requirements.append(requirement)
        return outcome

    def _without_contradictions(
        self, items: list[ExtractedItem], outcome: Ingested
    ) -> list[ExtractedItem]:
        """
        Drop offers that contradict a need from the same actor for the same resource.

        Args:
            items (list[ExtractedItem]): Everything the model read from one post.
            outcome (Ingested): Collects a line per dropped item.

        Returns:
            list[ExtractedItem]: What survives, with the need kept over the offer.

        Note:
            Matching is on the normalized actor name rather than the resolved actor, because
            this runs before resolution and the drift is within a single post — one name is
            the same string the model wrote twice.
        """
        needed = {
            (normalize(item.actor.name), item.resource_key)
            for item in items
            if item.direction == "needs"
        }
        surviving = []
        for item in items:
            key = (normalize(item.actor.name), item.resource_key)
            if item.direction == "offers" and key in needed:
                outcome.dropped.append(
                    f"{item.actor.name!r} cannot both need and offer {item.resource_key!r}"
                )
                continue
            surviving.append(item)
        return surviving

    def _build(
        self,
        item: ExtractedItem,
        observation: Observation,
        fallback_location: Location | None,
        extraction: Extraction,
    ) -> Requirement | None:
        """
        Turn one item into a requirement, or refuse it.

        Args:
            item (ExtractedItem): One thing needed or offered.
            observation (Observation): The post it came from.
            fallback_location (Location | None): Resolved from the post's overall geocode
                query, used when the item named no place of its own.
            extraction (Extraction): Supplies the confidence carried onto the requirement.

        Returns:
            Requirement | None: The stored requirement, or None when it has no place. A
                requirement nobody can reach is not actionable, and keeping it would inflate
                the demand a coordinator sees without giving them anywhere to go.
        """
        location = fallback_location
        if item.location_text.strip():
            location = (
                self.geocoder.resolve(
                    f"{item.location_text}, {observation.event.country_code}", observation.event
                )
                or fallback_location
            )
        if location is None:
            return None

        resolution = self.resolver.resolve(
            item.actor, observation, contacts=item.contacts, location=location
        )
        self._record_contacts(item.contacts, resolution.actor, observation)

        requirement = Requirement.objects.create(
            event=observation.event,
            actor=resolution.actor,
            direction=Direction.NEEDS if item.direction == "needs" else Direction.OFFERS,
            resource=self._resource(item.resource_key),
            free_text=item.resource[:300],
            quantity=item.quantity,
            unit=item.unit[:30],
            location=location,
            urgency=item.urgency if item.urgency in Urgency.values else Urgency.MEDIUM,
            status=RequirementStatus.OPEN,
            confidence=extraction.confidence,
            last_seen_at=observation.posted_at or timezone.now(),
        )
        requirement.evidence.add(observation)
        return requirement

    def _resource(self, key: str) -> ResourceType:
        """
        Map a guessed key onto the taxonomy, inventing a leaf when it is unknown.

        Args:
            key (str): The slug the model guessed.

        Returns:
            ResourceType: An existing type, or a new parentless one. A new leaf will not take
                part in category fallback until someone gives it a parent, which is the honest
                behaviour — a resource nobody classified cannot be substituted for another.
        """
        slug = normalize(key).replace(" ", "_")[:60] or "unclassified"
        resource, _ = ResourceType.objects.get_or_create(
            key=slug, defaults={"name": key[:120] or "Sin clasificar"}
        )
        return resource

    def _record_contacts(
        self, contacts: list[ExtractedContact], actor, observation: Observation
    ) -> None:
        """
        Store the ways to reach an actor, counting repeats rather than duplicating them.

        Note:
            `times_seen` is the confidence signal: a number written across five posts is
            almost certainly real, one appearing once may be an extraction slip. So a repeat
            increments rather than inserting.
        """
        for contact in contacts:
            value = contact.value.strip()
            if not value:
                continue
            point, created = ContactPoint.objects.get_or_create(
                actor=actor,
                kind=contact.kind,
                value=value[:300],
                defaults={
                    "raw_value": value[:300],
                    "payment_network": contact.network[:40],
                    "discovered_in": observation,
                    "confidence": 0.6,
                },
            )
            if not created:
                point.times_seen += 1
                point.confidence = min(1.0, 0.5 + 0.1 * point.times_seen)
                point.save(update_fields=["times_seen", "confidence"])
