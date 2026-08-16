"""
The matching pass: turning open requirements into proposed matches.

Runs as a batch allocation over the event's open requirements, per the data model doc:
pairwise greedy matching leaves needs uncovered that had a solution, so scores go into an
assignment problem (scipy Hungarian). Postgres stays the source of truth; the in-memory
structures are rebuilt and discarded every pass.

Candidate distances use geodesic (straight-line) kilometers for speed; the real road
distance from OSRM belongs to the enrichment of *accepted* proposals, not to candidate
generation over every pair.
"""

import math

import numpy as np
from scipy.optimize import linear_sum_assignment

from ayudagente.radar.choices import Direction, MatchStatus, RequirementStatus, Urgency
from ayudagente.radar.models import Match, Requirement
from ayudagente.radar.services.requirements import resource_family

# Beyond this, a pair needs a transport requirement to be actionable
DIRECT_DELIVERY_KM = 30.0
# How far a transporter plausibly drives to pick cargo up (dead-head leg)
TRANSPORT_PICKUP_KM = 250.0
# Pairs scoring below this are noise, not proposals
MIN_SCORE = 0.2

# Keyed by str: `Requirement.urgency` reaches us as a plain CharField value
URGENCY_WEIGHT: dict[str, float] = {
    Urgency.CRITICAL: 1.0,
    Urgency.HIGH: 0.8,
    Urgency.MEDIUM: 0.55,
    Urgency.LOW: 0.3,
}

TRANSPORT_KEY = "transporte"


def geodesic_km(a, b) -> float:
    """Haversine distance in km between two GEOS points (lon/lat)."""
    lon1, lat1, lon2, lat2 = map(math.radians, (a.x, a.y, b.x, b.y))
    h = (
        math.sin((lat2 - lat1) / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    )
    return 2 * 6371 * math.asin(math.sqrt(h))


def score_pair(need: Requirement, offer: Requirement, distance_km: float) -> float:
    """
    Score one need/offer pair in [0, 1]. Transparent on purpose — every factor is
    explainable in the match rationale.
    """
    urgency = URGENCY_WEIGHT[need.urgency]
    proximity = 1 / (1 + distance_km / 25)  # halves every ~25 km

    exact_resource = 1.0 if need.resource_id == offer.resource_id else 0.7

    if need.outstanding_quantity is None or offer.outstanding_quantity is None:
        quantity_fit = 0.6  # unknown amounts: usable but not preferred
    elif offer.outstanding_quantity <= 0:
        return 0.0
    else:
        covered = min(need.outstanding_quantity, offer.outstanding_quantity)
        quantity_fit = float(covered / need.outstanding_quantity)

    credibility = (need.confidence + offer.confidence) / 2

    return round(
        0.35 * urgency
        + 0.30 * proximity
        + 0.15 * exact_resource * quantity_fit
        + 0.20 * credibility,
        4,
    )


def _is_transport(requirement: Requirement) -> bool:
    resource = requirement.resource
    return resource.key == TRANSPORT_KEY or any(
        ancestor.key == TRANSPORT_KEY for ancestor in resource.ancestors()
    )


def _find_transport(need, offer, transports) -> Requirement | None:
    """
    A transport offer that can bridge offer → need: origin near the offer, destination
    near the need or not yet fixed (`destination` null = solver decides).
    """
    # A transport already routed to the need's area beats a destination-free one:
    # rank by (destination-free?, pickup distance) so fixed matching routes win ties.
    best, best_rank = None, (True, float("inf"))
    for transport in transports:
        origin_km = geodesic_km(transport.location.point, offer.location.point)
        if origin_km > TRANSPORT_PICKUP_KM:
            continue
        if transport.destination is not None:
            dest_km = geodesic_km(transport.destination.point, need.location.point)
            if dest_km > DIRECT_DELIVERY_KM:
                continue
        rank = (transport.destination is None, origin_km)
        if rank < best_rank:
            best, best_rank = transport, rank
    return best


def propose_match(
    need: Requirement,
    offer: Requirement,
    via_transport: Requirement | None = None,
    committed_quantity=None,
    distance_km: float | None = None,
    score: float | None = None,
    rationale: str = "",
) -> Match | None:
    """
    Create or refresh one proposed match, respecting the frozen-state invariant.

    Returns the match, or None when an existing match is past `proposed` — a human is
    already involved and the row must not be rewritten.
    """
    if need.direction != Direction.NEEDS or offer.direction != Direction.OFFERS:
        raise ValueError("need must have direction=needs and offer direction=offers")
    if via_transport is not None and not _is_transport(via_transport):
        raise ValueError("via_transport must be a transport-family requirement")

    if distance_km is None:
        distance_km = round(geodesic_km(need.location.point, offer.location.point), 1)
    if score is None:
        score = score_pair(need, offer, distance_km)

    existing = Match.objects.filter(need=need, offer=offer).first()
    if existing is not None and existing.is_frozen:
        return None

    if committed_quantity is None:
        outstanding_need = need.outstanding_quantity
        outstanding_offer = offer.outstanding_quantity
        if outstanding_need is not None and outstanding_offer is not None:
            committed_quantity = min(outstanding_need, outstanding_offer)

    match, _ = Match.objects.update_or_create(
        need=need,
        offer=offer,
        defaults={
            "via_transport": via_transport,
            "committed_quantity": committed_quantity,
            "distance_km": distance_km,
            "score": score,
            "rationale": rationale,
        },
    )
    return match


def run_matching_pass(event_id: int) -> dict:
    """
    Rebuild the event's proposed matches as one allocation problem.

    Steps: load open requirements → build compatible candidate pairs with scores →
    Hungarian assignment maximizing total score → write proposals (frozen rows untouched,
    stale proposals removed) → report needs with no reachable supply at all, the most
    valuable alert in the system.

    Returns:
        dict: `proposed` (created/updated match ids), `unreachable_need_ids`.
    """
    open_reqs = list(
        Requirement.objects.filter(
            event_id=event_id,
            status__in=(RequirementStatus.OPEN, RequirementStatus.PARTIAL),
        ).select_related("resource", "location", "destination", "actor")
    )

    transports = [r for r in open_reqs if _is_transport(r) and r.direction == Direction.OFFERS]
    needs = [
        r
        for r in open_reqs
        if r.direction == Direction.NEEDS and not r.is_saturated and not _is_transport(r)
    ]
    offers = [
        r
        for r in open_reqs
        if r.direction == Direction.OFFERS and not r.is_saturated and not _is_transport(r)
    ]

    families = {r.id: resource_family(r.resource) for r in offers}

    candidates: dict[tuple[int, int], dict] = {}
    for i, need in enumerate(needs):
        for j, offer in enumerate(offers):
            if need.resource_id not in families[offer.id]:
                continue
            km = geodesic_km(need.location.point, offer.location.point)
            transport = None
            if km > DIRECT_DELIVERY_KM:
                transport = _find_transport(need, offer, transports)
                if transport is None:
                    continue  # too far and nothing can move it
            score = score_pair(need, offer, km)
            if score >= MIN_SCORE:
                candidates[(i, j)] = {
                    "distance_km": round(km, 1),
                    "score": score,
                    "via_transport": transport,
                }

    proposed_ids: list[int] = []
    if candidates:
        cost = np.full((len(needs), len(offers)), 1.0)
        for (i, j), meta in candidates.items():
            cost[i, j] = 1.0 - meta["score"]
        rows, cols = linear_sum_assignment(cost)

        for i, j in zip(rows, cols, strict=True):
            meta = candidates.get((i, j))
            if meta is None:
                continue  # assignment landed on a non-candidate cell
            need, offer = needs[i], offers[j]
            transport_note = (
                f" vía transporte #{meta['via_transport'].id}" if meta["via_transport"] else ""
            )
            match = propose_match(
                need,
                offer,
                via_transport=meta["via_transport"],
                distance_km=meta["distance_km"],
                score=meta["score"],
                rationale=(
                    f"{offer.actor.canonical_name} ofrece {offer.resource.name} a "
                    f"{meta['distance_km']} km de la necesidad de "
                    f"{need.actor.canonical_name} (urgencia {need.urgency})"
                    f"{transport_note}. Score {meta['score']}."
                ),
            )
            if match is not None:
                proposed_ids.append(match.id)

    # Stale proposals: still `proposed` but not re-produced by this pass
    Match.objects.filter(need__event_id=event_id, status=MatchStatus.PROPOSED).exclude(
        id__in=proposed_ids
    ).delete()

    reachable = {i for (i, _j) in candidates}
    unreachable_need_ids = [needs[i].id for i in range(len(needs)) if i not in reachable]

    return {"proposed": proposed_ids, "unreachable_need_ids": unreachable_need_ids}
