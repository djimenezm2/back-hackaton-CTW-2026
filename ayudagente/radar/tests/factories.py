"""Minimal object builders for service tests. Plain functions, no factory library."""

from django.contrib.gis.geos import Point
from django.utils import timezone

from ayudagente.radar.choices import (
    ActorKind,
    Direction,
    GeocodeSource,
    HazardKind,
    LocationPrecision,
    Urgency,
)
from ayudagente.radar.models import Actor, Event, Location, Requirement, ResourceType

# Real coordinates, lon/lat
PEREIRA = Point(-75.6961, 4.8133, srid=4326)
DOSQUEBRADAS = Point(-75.6727, 4.8318, srid=4326)
QUIBDO = Point(-76.6611, 5.6947, srid=4326)
CALI = Point(-76.5320, 3.4516, srid=4326)


def make_event(**kwargs) -> Event:
    defaults = {
        "hazard": HazardKind.EARTHQUAKE,
        "name": "Sismo de prueba",
        "occurred_at": timezone.now(),
        "detection_source": "manual",
        "epicenter": PEREIRA,
    }
    defaults.update(kwargs)
    return Event.objects.create(**defaults)


def make_resource(key: str, name: str | None = None, parent=None, **kwargs) -> ResourceType:
    return ResourceType.objects.create(
        key=key, name=name or key.replace("_", " ").title(), parent=parent, **kwargs
    )


def make_location(point: Point, text: str, **kwargs) -> Location:
    defaults = {
        "precision": LocationPrecision.NEIGHBORHOOD,
        "raw_text": text,
        "text_norm": text.lower(),
        "source": GeocodeSource.MANUAL,
    }
    defaults.update(kwargs)
    return Location.objects.create(point=point, **defaults)


def make_actor(event: Event, name: str, **kwargs) -> Actor:
    now = timezone.now()
    defaults = {
        "kind": ActorKind.PERSON,
        "canonical_name": name,
        "name_norm": name.lower(),
        "first_seen_at": now,
        "last_seen_at": now,
    }
    defaults.update(kwargs)
    return Actor.objects.create(event=event, **defaults)


def make_requirement(
    event: Event,
    actor: Actor,
    resource: ResourceType,
    location: Location,
    direction: str = Direction.NEEDS,
    **kwargs,
) -> Requirement:
    defaults = {
        "urgency": Urgency.HIGH,
        "last_seen_at": timezone.now(),
        "confidence": 0.8,
    }
    defaults.update(kwargs)
    return Requirement.objects.create(
        event=event,
        actor=actor,
        resource=resource,
        location=location,
        direction=direction,
        **defaults,
    )
