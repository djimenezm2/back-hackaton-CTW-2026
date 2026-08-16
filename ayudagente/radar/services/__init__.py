"""
Deterministic service layer: the functions the agent calls as tools.

The split follows the handbook's rule — judgment belongs to the model, functions belong
here. Everything in this package is plain Python over Postgres/PostGIS and OSRM, callable
from LangGraph tools, Celery tasks or a shell alike.
"""

from ayudagente.radar.services.actors import (
    best_contact_point,
    get_actor,
    get_contact_points,
)
from ayudagente.radar.services.frontier import (
    build_search_query,
    create_harvest_job,
    get_frontier,
)
from ayudagente.radar.services.graph import (
    build_graph_payload,
    input_fingerprint,
    refresh_graph,
)
from ayudagente.radar.services.matching import (
    is_matchable_location,
    propose_match,
    run_matching_pass,
)
from ayudagente.radar.services.outreach import draft_outreach, match_participants
from ayudagente.radar.services.requirements import (
    find_admin_units,
    find_requirements,
    get_balance,
    resolve_resource,
    resource_catalog,
    resource_family,
    routable,
)
from ayudagente.radar.services.routing import RoutingError, plan_trip_stops, road_distance

__all__ = [
    "RoutingError",
    "best_contact_point",
    "build_graph_payload",
    "build_search_query",
    "create_harvest_job",
    "draft_outreach",
    "find_admin_units",
    "find_requirements",
    "get_actor",
    "get_balance",
    "get_contact_points",
    "get_frontier",
    "input_fingerprint",
    "is_matchable_location",
    "match_participants",
    "plan_trip_stops",
    "propose_match",
    "refresh_graph",
    "resolve_resource",
    "resource_catalog",
    "resource_family",
    "road_distance",
    "routable",
    "run_matching_pass",
]
