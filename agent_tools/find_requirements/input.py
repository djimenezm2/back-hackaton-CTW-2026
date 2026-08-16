"""
The argument schema, which is the half of the tool the model reads before calling it.

Field descriptions are prompt text, not documentation. They validate types only: a wrong
*value* — a resource that does not exist — is caught in the tool body against the database,
because only the database knows the catalog.
"""

from pydantic import BaseModel, Field

from agent_tools.find_requirements.constants import (
    DEFAULT_LIMIT,
    DIRECTION_VALUES,
    MAX_LIMIT,
    PRECISION_VALUES,
)


class FindRequirementsInput(BaseModel):
    """Arguments for `find_requirements`. Descriptions here are what the model reads."""

    event_id: int = Field(description="Event to search within. Requirements never cross events.")
    direction: str = Field(
        description=(
            f"What to look for: one of {DIRECTION_VALUES}. Use 'needs' to find who is "
            "asking for something, 'offers' to find who has it."
        )
    )
    resource_key: str | None = Field(
        default=None,
        description=(
            "Which resource, as its slug ('agua_potable') or its Spanish name ('Agua "
            "potable'). The catalog is in Spanish, so do not translate — an English word "
            "will not match. If unsure, call once without this argument and read the "
            "`resource_key` values that come back. Search walks the resource tree in both "
            "directions, so a specific item also finds its general category, and the "
            "other way round. Omit to search every resource."
        ),
    )
    place: str | None = Field(
        default=None,
        description=(
            "An administrative area, by name ('Quibdó') or national code ('27001'). It "
            "includes everything below it, so naming a region covers its towns. Prefer "
            "this over lat/lon: it resolves against the official gazetteer, and "
            "coordinates recalled from memory are wrong often enough to matter."
        ),
    )
    text: str | None = Field(
        default=None,
        description=(
            "Words to look for in the original wording, for detail the resource catalog is "
            "too coarse to carry — 'leche de fórmula' lives inside the 'alimentos' "
            "category. Filters, never reorders. Spanish, like the posts."
        ),
    )
    lat: float | None = Field(
        default=None,
        description=(
            "Latitude of a reference point. Ordering switches from urgency to distance. "
            "Use only for a spot with no administrative name, such as a coordinate a "
            "responder reported."
        ),
    )
    lon: float | None = Field(
        default=None, description="Longitude of the reference point. Required with lat."
    )
    radius_km: float | None = Field(
        default=None,
        description="With lat/lon, discard anything farther than this many kilometres.",
    )
    min_precision: str | None = Field(
        default=None,
        description=(
            f"Discard locations coarser than this: one of {PRECISION_VALUES}, ordered "
            "coarsest to finest ('admin_1' is a region, 'admin_2' a town). Use 'admin_2' "
            "or finer before proposing a delivery — a coarser dot names an area, not a "
            "place a truck can reach."
        ),
    )
    limit: int = Field(
        default=DEFAULT_LIMIT,
        description=f"Maximum rows to return, capped at {MAX_LIMIT}.",
    )
