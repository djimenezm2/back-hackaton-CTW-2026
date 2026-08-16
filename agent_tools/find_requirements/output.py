"""
Turning requirement rows into the dicts the model sees.

Nothing here queries or decides. It exists so the tool body reads as a sequence of guards
and one call, instead of guards and a paragraph of dictionary building.
"""

from agent_tools.find_requirements.constants import NOTE_CHARS


def serialize(requirement) -> dict:
    """
    Flatten one requirement into the fields a model needs to decide.

    Returns:
        dict: Ids to act on, names to write with, numbers to compare. No Django objects —
            one serialized by accident drags every field into the context window.
    """
    location = requirement.location
    admin_unit = location.admin_unit
    outstanding = requirement.outstanding_quantity

    row = {
        "id": requirement.id,
        "actor_id": requirement.actor_id,
        "actor": requirement.actor.canonical_name,
        "actor_kind": requirement.actor.kind,
        "resource": requirement.resource.name,
        "resource_key": requirement.resource.key,
        "outstanding": float(outstanding) if outstanding is not None else None,
        "unit": requirement.unit or None,
        "urgency": requirement.urgency,
        "status": requirement.status,
        "confidence": round(requirement.confidence, 2),
        "place": location.raw_text,
        "precision": location.precision,
        "municipality": admin_unit.name if admin_unit else None,
    }

    if requirement.free_text:
        row["note"] = requirement.free_text[:NOTE_CHARS]

    # Only transport carries a destination; for everything else it is null by design
    if requirement.destination_id is not None:
        row["destination"] = requirement.destination.raw_text

    distance_m = getattr(requirement, "distance_m", None)
    if distance_m is not None:
        row["distance_km"] = round(distance_m.m / 1000, 1)

    return row
