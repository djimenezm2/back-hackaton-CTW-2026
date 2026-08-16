"""
The search frontier: the scoreboard the agent reads and the jobs it writes.

This is the whole world of the frontier agent. It reads `FrontierNode` and writes
`HarvestJob`, and it never touches an `Observation` — reading a scoreboard and deciding
where to look next is judgment; reading a post is a function.

Note:
    The query string is built here, from the event lexicon, and never by the model. Two
    guarantees depend on that: every query carries a real toponym, and the terms belonging
    to other concurrent emergencies are excluded. Both are one hallucination away from gone
    if the model composes the string.
"""

from ayudagente.radar.choices import (
    DecisionSource,
    HarvestTarget,
    JobStatus,
    NodeStatus,
    Platform,
)
from ayudagente.radar.models import AdminUnit, Event, FrontierNode, HarvestJob

# One Apify actor per platform. The agent picks a target, never an implementation.
APIFY_ACTOR_BY_PLATFORM = {
    Platform.X: "apidojo/tweet-scraper",
    Platform.INSTAGRAM: "apify/instagram-scraper",
    Platform.FACEBOOK: "apify/facebook-posts-scraper",
    Platform.TIKTOK: "clockworks/tiktok-scraper",
}

MAX_QUERY_TERMS = 12


def get_frontier(event_id: int, limit: int = 60) -> list[FrontierNode]:
    """
    The event's watch targets, best quality first, unexplored ones included.

    Args:
        event_id (int): The event whose frontier to read.
        limit (int): Row cap. A few dozen rows is the whole point — this fits in a prompt.

    Returns:
        list[FrontierNode]: Active nodes ordered by `yield_rate`, highest first.

    Note:
        Paused and exhausted nodes are excluded: they are not decisions the agent still has
        to make. Unexplored nodes stay in with a yield of zero and are flagged rather than
        ranked up, because forcing exploration is the caller's policy, not the ordering's.
    """
    return list(
        FrontierNode.objects.filter(event_id=event_id, status=NodeStatus.ACTIVE)
        .select_related("admin_unit", "actor")
        .order_by("-yield_rate", "-updated_at")[:limit]
    )


def build_search_query(event: Event, admin_unit: AdminUnit) -> str:
    """
    Compose the query string for a place sweep, anchored and de-conflicted.

    Args:
        event (Event): Source of the lexicon — hashtags, nicknames and negatives.
        admin_unit (AdminUnit): The toponym that anchors the query.

    Returns:
        str: Terms joined for the platform's search syntax, with other emergencies' terms
            excluded.

    Note:
        The toponym is not optional and not the model's to choose. Without it a query for
        "earthquake help" pulls in every other country's earthquake.
    """
    lexicon = event.lexicon or {}
    terms = [admin_unit.name]
    terms += list(lexicon.get("hashtags", []))[:4]
    terms += list(lexicon.get("nicknames", []))[:4]

    query = " OR ".join(f'"{term}"' for term in terms[:MAX_QUERY_TERMS])
    negatives = " ".join(f'-"{term}"' for term in list(lexicon.get("negatives", []))[:6])
    return f"{query} {negatives}".strip()


def create_harvest_job(
    event_id: int,
    node_id: int,
    rationale: str,
    target_kind: str = HarvestTarget.SEARCH,
    decided_by: str = DecisionSource.AGENT,
) -> HarvestJob:
    """
    Turn a decision about where to look next into an executable, auditable job.

    Args:
        event_id (int): The event the job belongs to.
        node_id (int): The frontier node being harvested; it supplies platform and target.
        rationale (str): Why this target, in plain text. Mandatory.
        target_kind (str): A `HarvestTarget` value — a place sweep or the deep pass.
        decided_by (str): A `DecisionSource` value.

    Returns:
        HarvestJob: Pending, with the exact payload a worker will send.

    Raises:
        ValueError: When the event is not harvestable, when the node does not belong to it,
            when the platform has no configured Apify actor, or when `rationale` is empty.

    Note:
        `rationale` is refused when blank rather than defaulted. It is the only record of
        why the agent spent a pass here, and an empty one makes both debugging and the
        dashboard useless.
    """
    if not rationale or not rationale.strip():
        raise ValueError("rationale is mandatory: every agent decision records why")

    event = Event.objects.filter(id=event_id).first()
    if event is None:
        raise ValueError(f"event {event_id} does not exist")
    if not event.is_harvestable:
        raise ValueError(f"event {event_id} is {event.status} and accepts no new jobs")

    node = (
        FrontierNode.objects.select_related("admin_unit", "actor")
        .filter(id=node_id, event_id=event_id)
        .first()
    )
    if node is None:
        raise ValueError(f"frontier node {node_id} does not belong to event {event_id}")

    apify_actor = APIFY_ACTOR_BY_PLATFORM.get(Platform(node.platform))
    if apify_actor is None:
        raise ValueError(f"no Apify actor configured for platform {node.platform!r}")

    # The check constraint guarantees exactly one target, but the types do not know that
    if node.actor is not None:
        actor_input = {"handle": node.actor.canonical_name, "resultsLimit": 100}
    elif node.admin_unit is not None:
        actor_input = {"searchQuery": build_search_query(event, node.admin_unit), "maxItems": 100}
    else:
        raise ValueError(f"frontier node {node_id} watches neither a place nor an account")

    return HarvestJob.objects.create(
        event=event,
        node=node,
        platform=node.platform,
        target_kind=target_kind,
        apify_actor=apify_actor,
        actor_input=actor_input,
        decided_by=decided_by,
        rationale=rationale.strip(),
        status=JobStatus.PENDING,
    )
