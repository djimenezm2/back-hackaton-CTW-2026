"""
What every tool needs: one failure shape, and the lookups more than one tool repeats.

A tool never raises *to the model*. An exception reaching the caller becomes an opaque
trace, while a returned value with an `error` and a `hint` is something the model can read
and correct on the next turn.

Inside a tool, argument resolution signals a bad argument by raising `ToolInputError` and
the tool body catches it once. That keeps the guards readable as a straight sequence — and,
unlike returning `(value, error)` pairs, it leaves the resolved values properly typed
rather than perpetually optional.
"""

from ayudagente.radar.models import AdminUnit, Event, ResourceType
from ayudagente.radar.services import find_admin_units, resolve_resource, resource_catalog

# A miss should show the whole taxonomy; the cap is a backstop, not an expectation
MAX_CATALOG_ROWS = 40


def failure(error: str, hint: str | None = None, **extra) -> dict:
    """
    Build the shape every failure returns.

    Args:
        error (str): What went wrong, in the model's terms.
        hint (str | None): What to do instead. Omit when the error already says it.
        **extra: Data the caller needs in order to retry — `available`, `candidates`.

    Returns:
        dict: Always carries `error`, so checking for that key is enough to branch on.
    """
    payload = {"error": error}
    if hint:
        payload["hint"] = hint
    payload.update(extra)
    return payload


class ToolInputError(Exception):
    """
    A bad argument, carrying the payload the tool should return.

    Note:
        Never allowed to escape a tool. Each tool catches it and returns `payload`, adding
        whatever empty collection its own contract promises.
    """

    def __init__(self, payload: dict):
        super().__init__(payload.get("error", "invalid argument"))
        self.payload = payload


def get_event(event_id: int) -> Event:
    """
    Fetch an event by id.

    Raises:
        ToolInputError: When it does not exist. Reported rather than answered with an empty
            list, because "no needs found" and "that event does not exist" lead the agent
            to opposite conclusions.
    """
    event = Event.objects.filter(id=event_id).only("id", "country_code", "status").first()
    if event is None:
        raise ToolInputError(failure(f"event {event_id} does not exist"))
    return event


def resolve_resource_arg(resource_key: str) -> ResourceType:
    """
    Resolve a resource by slug or display name.

    Raises:
        ToolInputError: With `available` listing the valid keys. The taxonomy is in Spanish
            and lives in a table that changes mid-emergency, so it can be neither
            translated nor frozen into a prompt.
    """
    resource = resolve_resource(resource_key)
    if resource is None:
        raise ToolInputError(
            failure(
                f"unknown resource {resource_key!r}",
                "pick a key from `available`, or omit the argument to search everything",
                available=resource_catalog(limit=MAX_CATALOG_ROWS),
            )
        )
    return resource


def resolve_place_arg(place: str, country_code: str) -> AdminUnit:
    """
    Resolve a place name or national code within one country.

    Raises:
        ToolInputError: With `candidates` when a name matches several units. Place names
            repeat across regions, and picking the first silently routes aid to the wrong
            one — a failure nobody notices until the truck arrives.
    """
    matches = find_admin_units(place, country_code=country_code)
    if not matches:
        raise ToolInputError(
            failure(
                f"no administrative unit matches {place!r}",
                "use the name as the official gazetteer spells it, or its national code",
            )
        )
    if len(matches) > 1:
        raise ToolInputError(
            failure(
                f"{place!r} matches {len(matches)} administrative units",
                "call again with the national code of the one you mean",
                candidates=[
                    {
                        "code": unit.code,
                        "name": unit.name,
                        "level": unit.level,
                        "parent": unit.parent.name if unit.parent else None,
                    }
                    for unit in matches
                ],
            )
        )
    return matches[0]
