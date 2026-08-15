"""
Deterministic service layer: the functions the agent calls as tools.

The split follows the handbook's rule — judgment belongs to the model, functions belong
here. Everything in this package is plain Python over Postgres/PostGIS and OSRM, callable
from LangGraph tools, Celery tasks or a shell alike.
"""

from ayudagente.radar.services.matching import propose_match, run_matching_pass
from ayudagente.radar.services.outreach import draft_outreach
from ayudagente.radar.services.requirements import (
    find_requirements,
    get_balance,
    resource_family,
)
from ayudagente.radar.services.routing import plan_trip_stops, road_distance

__all__ = [
    'draft_outreach',
    'find_requirements',
    'get_balance',
    'plan_trip_stops',
    'propose_match',
    'resource_family',
    'road_distance',
    'run_matching_pass',
]
