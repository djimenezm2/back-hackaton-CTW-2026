"""
Read-only JSON endpoints: the graph snapshot the web frontend loads at startup.

The graph is served from `GraphSnapshot`, persisted and kept current by write triggers —
a fetch is a row read, never a recomputation. Plain Django views on purpose; no DRF in
the stack and none needed for hand-shaped cacheable reads.
"""

from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_GET

from ayudagente.radar.choices import EventStatus
from ayudagente.radar.models import Event, GraphSnapshot
from ayudagente.radar.services.graph import _point, refresh_graph


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
    The event's stored graph in one response: nodes, edges, and when it was built.

    Writes keep the snapshot current through the rebuild triggers, so this endpoint only
    computes anything on the very first fetch of an event (or after its snapshot was
    deleted); every other call is a single-row read of the persisted payload.
    """
    event = get_object_or_404(Event, id=event_id)

    snapshot = GraphSnapshot.objects.filter(event=event).first()
    if snapshot is None:
        snapshot, _rebuilt = refresh_graph(event.id)

    payload = dict(snapshot.payload)
    payload["built_at"] = snapshot.built_at.isoformat()
    return JsonResponse(payload)
