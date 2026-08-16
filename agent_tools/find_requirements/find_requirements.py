"""
`find_requirements` as an agent tool.

The wrapper does four things and no more: it turns the model's JSON scalars into the
objects the service expects, it caps the rows, it flattens Django objects into plain dicts,
and it turns failures into values the agent can read. Every rule about *which* requirements
are still worth acting on — closed windows, merged actors, saturation — lives in
`ayudagente.radar.services.requirements` and is deliberately not repeated here.

See:
    `docs/agent-tools.md` for the layer contract.
"""

from django.contrib.gis.geos import Point
from langchain_core.tools import tool

from agent_tools.find_requirements.constants import DEFAULT_LIMIT, MAX_LIMIT
from agent_tools.find_requirements.input import FindRequirementsInput
from agent_tools.find_requirements.output import serialize
from agent_tools.shared import (
    ToolInputError,
    failure,
    get_event,
    resolve_place_arg,
    resolve_resource_arg,
)
from ayudagente.radar.services import find_requirements as find_requirements_service


@tool("find_requirements", args_schema=FindRequirementsInput)
def find_requirements(
    event_id: int,
    direction: str,
    resource_key: str | None = None,
    place: str | None = None,
    text: str | None = None,
    lat: float | None = None,
    lon: float | None = None,
    radius_km: float | None = None,
    min_precision: str | None = None,
    limit: int = DEFAULT_LIMIT,
) -> dict:
    """
    Search the open needs or offers of an event, most urgent first.

    Returns only what is still actionable: requirements whose time window has not closed,
    that are not already fully covered, and that belong to actors not merged into another.
    A requirement missing from the results is not necessarily absent — it may be saturated,
    which means it should not receive more.

    Narrow by `place` for an administrative area, by `resource_key` for a category, and by
    `text` for wording the categories are too coarse to hold. Passing lat/lon instead
    reorders the results by distance rather than urgency.

    Quantities are in `outstanding`, meaning what is still uncovered, in `unit`. A null
    outstanding means the amount was never stated, not that it is zero. Distances are
    straight-line kilometres; use `road_distance` before committing to a delivery.

    Failures come back as `error` with the data needed to retry: `available` lists the
    valid resource keys, `candidates` lists the places a name matched. When `truncated` is
    true there are more rows than were returned — narrow the search rather than raise the
    limit.
    """
    if (lat is None) != (lon is None):
        return failure(
            "lat and lon must be given together",
            "pass both to search around a point, or neither to search the event",
            requirements=[],
        )

    if radius_km is not None and lat is None:
        return failure(
            "radius_km needs a reference point",
            "pass lat and lon alongside it",
            requirements=[],
        )

    try:
        event = get_event(event_id)
        resource = resolve_resource_arg(resource_key) if resource_key is not None else None
        # Scoped to the event's country: `code` is only unique per country and level
        admin_unit = resolve_place_arg(place, event.country_code) if place is not None else None
    except ToolInputError as exc:
        return {**exc.payload, "requirements": []}

    near = Point(lon, lat, srid=4326) if lat is not None and lon is not None else None
    limit = max(1, min(limit, MAX_LIMIT))

    try:
        # One extra row is how we learn there was more without paying for a count query
        rows = list(
            find_requirements_service(
                event_id=event_id,
                direction=direction,
                resource=resource,
                admin_unit=admin_unit,
                text=text,
                near=near,
                radius_km=radius_km,
                min_precision=min_precision,
                limit=limit + 1,
            )
        )
    except ValueError as exc:
        return failure(str(exc), requirements=[])

    return {
        "count": min(len(rows), limit),
        "truncated": len(rows) > limit,
        "requirements": [serialize(r) for r in rows[:limit]],
    }
