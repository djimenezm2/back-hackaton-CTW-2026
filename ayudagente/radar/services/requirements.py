"""
Queries over supply and demand.

These are read tools: they never mutate state. Matching compatibility walks the
`ResourceType` hierarchy so a need for "colchonetas" can be met by an offer of "cobijas y
ropa de cama" when nothing closer exists.
"""

from django.contrib.gis.db.models.functions import Distance
from django.contrib.gis.geos import Point
from django.contrib.gis.measure import D
from django.db.models import DecimalField, F, Q, QuerySet, Sum, Value
from django.db.models.functions import Coalesce

from ayudagente.radar.choices import Direction, LocationPrecision, RequirementStatus
from ayudagente.radar.models import Requirement, ResourceType

OPEN_STATUSES = (RequirementStatus.OPEN, RequirementStatus.PARTIAL)


def resource_family(resource: ResourceType) -> set[int]:
    """
    IDs of every resource compatible with the given one: itself, ancestors, descendants.

    An offer of the parent category can satisfy a need for the specific item, and a
    specific offer can satisfy a generic need.
    """
    ids = {resource.id}
    ids.update(ancestor.id for ancestor in resource.ancestors())

    pending = [resource]
    while pending:
        current = pending.pop()
        for child in current.children.all():
            if child.id not in ids:
                ids.add(child.id)
                pending.append(child)
    return ids


def find_requirements(
    event_id: int,
    direction: str,
    resource: ResourceType | None = None,
    near: Point | None = None,
    radius_km: float | None = None,
    min_precision: str | None = None,
    only_unsaturated: bool = True,
    limit: int = 50,
) -> QuerySet[Requirement]:
    """
    Open requirements matching direction and resource family, nearest first.

    Args:
        event_id: The event to search within — requirements never cross events.
        direction: `Direction.NEEDS` or `Direction.OFFERS`.
        resource: When given, expands to its whole compatible family.
        near: Reference point; results get annotated with `distance_m` and ordered by it.
        radius_km: With `near`, hard cutoff using the spatial index.
        min_precision: Minimum `LocationPrecision` — filters out department-sized dots.
        only_unsaturated: Drop requirements already fully covered.
    """
    qs = Requirement.objects.filter(
        event_id=event_id, direction=direction, status__in=OPEN_STATUSES
    ).select_related('resource', 'actor', 'location', 'destination')

    if resource is not None:
        qs = qs.filter(resource_id__in=resource_family(resource))

    if min_precision is not None:
        scale = list(LocationPrecision.values)
        allowed = scale[scale.index(min_precision):]
        qs = qs.filter(location__precision__in=allowed)

    if only_unsaturated:
        qs = qs.exclude(
            Q(quantity__isnull=False) & Q(covered_quantity__gte=F('quantity'))
        ).exclude(status=RequirementStatus.COVERED)

    if near is not None:
        if radius_km is not None:
            qs = qs.filter(location__point__dwithin=(near, D(km=radius_km)))
        qs = qs.annotate(distance_m=Distance('location__point', near)).order_by(
            'distance_m'
        )
    else:
        qs = qs.order_by('-urgency', '-confidence')

    return qs[:limit]


def get_balance(event_id: int, resource: ResourceType | None = None) -> list[dict]:
    """
    Aggregate deficit/surplus per resource per municipality.

    Returns one row per (resource, admin unit, direction) with outstanding quantities —
    the network-wide view behind "what should center X ask for".
    """
    qs = Requirement.objects.filter(event_id=event_id, status__in=OPEN_STATUSES)
    if resource is not None:
        qs = qs.filter(resource_id__in=resource_family(resource))

    rows = (
        qs.values(
            'resource_id',
            'resource__name',
            'direction',
            'location__admin_unit_id',
            'location__admin_unit__name',
        )
        .annotate(
            total=Coalesce(
                Sum(F('quantity') - F('covered_quantity')),
                Value(0),
                output_field=DecimalField(max_digits=14, decimal_places=2),
            ),
            count=Sum(Value(1)),
        )
        .order_by('resource__name', 'location__admin_unit__name')
    )

    return [
        {
            'resource_id': row['resource_id'],
            'resource': row['resource__name'],
            'direction': row['direction'],
            'admin_unit_id': row['location__admin_unit_id'],
            'admin_unit': row['location__admin_unit__name'] or 'sin ubicar',
            'outstanding': row['total'],
            'requirements': row['count'],
        }
        for row in rows
    ]
