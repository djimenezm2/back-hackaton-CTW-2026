"""
Event endpoints: the list, one event's header, and the whole graph in a single response.

The graph endpoint is deliberately not paginated. A map is only readable when it is complete —
half the needs of a city is a worse picture than none — and at pilot size the whole thing is a
few hundred nodes. When it stops fitting, that is the moment to page it, not before.
"""

from django.db.models import Prefetch
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_GET

from ayudagente.radar.choices import Direction, EventStatus, OutreachStatus
from ayudagente.radar.models import (
    Actor,
    Event,
    Match,
    Observation,
    Outreach,
    Requirement,
)
from ayudagente.radar.views import payloads
from ayudagente.radar.views.policy import OPEN_REQUIREMENT_STATUSES, VISIBLE_MATCH_STATUSES


@require_GET
def event_list(request):
    """Active events, newest first — the frontend's entry point."""
    events = Event.objects.filter(status=EventStatus.ACTIVE).order_by("-occurred_at")
    return JsonResponse({"events": [payloads.event_brief(event) for event in events]})


@require_GET
def event_detail(request, event_id: int):
    """One event with the counts a dashboard header shows."""
    event = get_object_or_404(Event, id=event_id)
    return JsonResponse(payloads.event_detail(event, _summary(event)))


@require_GET
def event_graph(request, event_id: int):
    """
    The whole graph for one event: actors as nodes, matches as edges, open requirements
    attached to their node. Read fresh from the database on every call — "real time" here
    means no snapshot lag, not a socket.
    """
    event = get_object_or_404(Event, id=event_id)

    open_requirements = Prefetch(
        "requirements",
        queryset=Requirement.objects.filter(status__in=OPEN_REQUIREMENT_STATUSES).select_related(
            "resource", "destination", "location"
        ),
        to_attr="open_requirements",
    )
    actors = (
        Actor.objects.filter(event=event, merged_into__isnull=True)
        .select_related("location", "location__admin_unit")
        .prefetch_related(open_requirements)
    )

    matches = Match.objects.filter(
        need__event=event, status__in=VISIBLE_MATCH_STATUSES
    ).select_related(
        "need__actor",
        "need__resource",
        "offer__actor",
        "via_transport__actor",
    )

    return JsonResponse(
        {
            "event": {
                "id": event.id,
                "name": event.name,
                "epicenter": payloads.point(event.epicenter),
            },
            "nodes": [_node(actor) for actor in actors],
            "edges": [_edge(match) for match in matches],
        }
    )


def _node(actor: Actor) -> dict:
    """
    One actor as a graph node, with its open requirements attached.

    Note:
        An actor often has no resolved location of its own while its requirements do, so the
        point falls back to the first open requirement's. The map still needs a dot, and a
        node without one silently disappears from the picture.
    """
    # `open_requirements` is the Prefetch's to_attr; getattr keeps type checkers happy.
    open_reqs: list[Requirement] = getattr(actor, "open_requirements", [])
    location = actor.location or (open_reqs[0].location if open_reqs else None)

    return {
        "id": actor.id,
        "name": actor.canonical_name,
        "kind": actor.kind,
        "credibility": actor.credibility,
        "verified": actor.verified,
        "location": payloads.point(location.point) if location else None,
        "precision": location.precision if location else None,
        "admin_unit": (location.admin_unit.name if location and location.admin_unit else None),
        "requirements": [payloads.requirement_brief(req) for req in open_reqs],
    }


def _edge(match: Match) -> dict:
    """One match as an edge, always pointing from the offer to the need."""
    return {
        "id": match.id,
        "from_actor": match.offer.actor_id,
        "to_actor": match.need.actor_id,
        "resource": match.need.resource.name,
        "status": match.status,
        "score": match.score,
        "distance_km": match.distance_km,
        "committed_quantity": payloads.number(match.committed_quantity),
        "via_transport_actor": (match.via_transport.actor_id if match.via_transport else None),
        "rationale": match.rationale,
    }


def _summary(event: Event) -> dict:
    """
    The counts a header shows.

    Note:
        `needs` and `offers` count open requirements, not all of them, so they answer "what is
        outstanding" rather than "what has ever been seen". `unread_observations` is the one
        that says whether the pipeline is behind.
    """
    open_requirements = Requirement.objects.filter(
        event=event, status__in=OPEN_REQUIREMENT_STATUSES
    )
    observations = Observation.objects.filter(event=event)

    return {
        "actors": Actor.objects.filter(event=event, merged_into__isnull=True).count(),
        "needs": open_requirements.filter(direction=Direction.NEEDS).count(),
        "offers": open_requirements.filter(direction=Direction.OFFERS).count(),
        "requirements": Requirement.objects.filter(event=event).count(),
        "matches": Match.objects.filter(
            need__event=event, status__in=VISIBLE_MATCH_STATUSES
        ).count(),
        "observations": observations.count(),
        "unread_observations": observations.filter(extraction__isnull=True).count(),
        "outreach_drafts": Outreach.objects.filter(
            target_actor__event=event, status=OutreachStatus.DRAFT
        ).count(),
    }
