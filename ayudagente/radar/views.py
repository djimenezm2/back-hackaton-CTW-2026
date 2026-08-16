"""
Read-only JSON endpoints: the graph snapshot the web frontend loads at startup.

Plain Django views on purpose — these are cache-friendly reads with hand-shaped payloads;
no DRF in the stack and none needed for that.
"""

from django.db.models import Prefetch
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_GET

from ayudagente.radar.choices import EventStatus, MatchStatus, RequirementStatus
from ayudagente.radar.models import Actor, Event, Match, Requirement

OPEN_REQUIREMENT_STATUSES = (RequirementStatus.OPEN, RequirementStatus.PARTIAL)
VISIBLE_MATCH_STATUSES = (
    MatchStatus.PROPOSED,
    MatchStatus.CONTACTED,
    MatchStatus.CONFIRMED,
    MatchStatus.DELIVERED,
)


@require_GET
def event_list(request):
    """Active events, newest first — the frontend's entry point."""
    events = Event.objects.filter(status=EventStatus.ACTIVE).order_by("-occurred_at")
    return JsonResponse(
        {
            "events": [
                {
                    "id": event.id,
                    "name": event.name,
                    "hazard": event.hazard,
                    "occurred_at": event.occurred_at.isoformat(),
                    "magnitude": event.magnitude,
                    "epicenter": _point(event.epicenter),
                }
                for event in events
            ]
        }
    )


@require_GET
def event_graph(request, event_id: int):
    """
    The whole graph for one event in a single response: actors as nodes, matches as
    edges, open requirements attached to their node. Fresh from the database on every
    call — "real time" here means no snapshot lag, not a socket.
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

    nodes = []
    for actor in actors:
        # `open_requirements` is the Prefetch's to_attr; getattr keeps type checkers happy.
        open_reqs: list[Requirement] = getattr(actor, "open_requirements", [])
        # An actor often has no resolved location of its own while its requirements do;
        # the map still needs a dot, so fall back to the first open requirement's point.
        location = actor.location
        if location is None and open_reqs:
            location = open_reqs[0].location
        nodes.append(
            {
                "id": actor.id,
                "name": actor.canonical_name,
                "kind": actor.kind,
                "credibility": actor.credibility,
                "verified": actor.verified,
                "location": _point(location.point) if location else None,
                "precision": location.precision if location else None,
                "admin_unit": (
                    location.admin_unit.name if location and location.admin_unit else None
                ),
                "requirements": [_requirement(req) for req in open_reqs],
            }
        )

    matches = Match.objects.filter(
        need__event=event, status__in=VISIBLE_MATCH_STATUSES
    ).select_related(
        "need__actor",
        "need__resource",
        "offer__actor",
        "via_transport__actor",
    )
    edges = [
        {
            "id": match.id,
            "from_actor": match.offer.actor_id,
            "to_actor": match.need.actor_id,
            "resource": match.need.resource.name,
            "status": match.status,
            "score": match.score,
            "distance_km": match.distance_km,
            "committed_quantity": _number(match.committed_quantity),
            "via_transport_actor": (match.via_transport.actor_id if match.via_transport else None),
            "rationale": match.rationale,
        }
        for match in matches
    ]

    return JsonResponse(
        {
            "event": {
                "id": event.id,
                "name": event.name,
                "epicenter": _point(event.epicenter),
            },
            "nodes": nodes,
            "edges": edges,
        }
    )


def _point(point):
    if point is None:
        return None
    return {"lat": point.y, "lon": point.x}


def _number(value):
    return float(value) if value is not None else None


def _requirement(req: Requirement) -> dict:
    return {
        "id": req.id,
        "direction": req.direction,
        "resource": req.resource.name,
        "resource_key": req.resource.key,
        "free_text": req.free_text,
        "urgency": req.urgency,
        "status": req.status,
        "quantity": _number(req.quantity),
        "covered_quantity": _number(req.covered_quantity),
        "outstanding": _number(req.outstanding_quantity),
        "unit": req.unit,
        "destination": _point(req.destination.point) if req.destination else None,
        "confidence": req.confidence,
    }
