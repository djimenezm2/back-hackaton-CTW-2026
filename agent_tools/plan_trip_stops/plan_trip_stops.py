"""
`plan_trip_stops` as an agent tool.

The division of labour is the whole design: the caller decides *what* goes on the truck,
this decides *in what order* to visit. Asking a model to sequence stops over real roads is
asking it to do arithmetic it cannot check; asking it which shelters matter is judgment.
"""

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from agent_tools.shared import failure
from ayudagente.radar.models import Requirement
from ayudagente.radar.services import RoutingError
from ayudagente.radar.services import plan_trip_stops as plan_trip_stops_service

# OSRM's trip solver is exponential in the worst case, and a truck's day is finite anyway
MAX_STOPS = 10


class PlanTripStopsInput(BaseModel):
    """Arguments for `plan_trip_stops`."""

    requirement_ids: list[int] = Field(
        description=(
            "Two to ten requirement ids, in any order. The first is treated as the "
            "starting point; the rest are resequenced. Their locations are the stops."
        )
    )


@tool("plan_trip_stops", args_schema=PlanTripStopsInput)
def plan_trip_stops(requirement_ids: list[int]) -> dict:
    """
    Put a set of stops into the shortest driving order.

    Give the requirements a vehicle has to visit; the first id is where the trip starts.
    Returns them resequenced with `total_km` and `total_min` for the whole route.

    This orders stops, it does not choose them: deciding what a truck carries and who it
    serves is yours. Ten stops is the ceiling.
    """
    if not 2 <= len(requirement_ids) <= MAX_STOPS:
        return failure(
            f"a trip needs between 2 and {MAX_STOPS} stops, got {len(requirement_ids)}",
            "split a longer route into separate trips",
        )

    found = {
        r.id: r
        for r in Requirement.objects.select_related("location", "actor").filter(
            id__in=requirement_ids
        )
    }
    missing = [rid for rid in requirement_ids if rid not in found]
    if missing:
        return failure(f"requirements not found: {missing}")

    # Order is meaningful — the caller's first id is the origin
    stops = [
        {
            "point": found[rid].location.point,
            "requirement_id": rid,
            "label": found[rid].location.raw_text,
            "actor": found[rid].actor.canonical_name,
        }
        for rid in requirement_ids
    ]

    try:
        trip = plan_trip_stops_service(stops)
    except (RoutingError, OSError, ValueError) as exc:
        return failure(
            f"routing unavailable: {exc}",
            "visit the stops in the order given and say the sequence is not optimized",
        )

    return {
        "total_km": trip["total_km"],
        "total_min": trip["total_min"],
        "ordered_stops": [
            {
                "position": position,
                "requirement_id": stop["requirement_id"],
                "actor": stop["actor"],
                "place": stop["label"],
            }
            for position, stop in enumerate(trip["ordered_stops"], start=1)
        ],
    }
