"""
The fixed route one observation walks, as a retryable unit of work.

The whole sequence lives inside a single task rather than a chain of five. Five tasks would
mean five round trips through the broker and state threaded between them, and a failure at
step four would leave the question of whether to repeat step one — which is the expensive one.
Inside one task the answer is already settled: the `Extraction` is written the moment the
model answers, so a retry resumes past it.

The order is plain Python and the judgment inside each step belongs to the model. That is the
architecture, not an implementation detail: fifty observations process in parallel under a
concurrency cap, a rate limit retries one task rather than corrupting an agent's history, and
a bad field is diagnosed by reading one step's output.

Note:
    Rate limits are retried by the task rather than waited on inside the SDK. A wait long
    enough to clear a minute-scale quota would hold a worker idle, and the queue can hold
    the work for nothing instead.
"""

import logging

from celery import shared_task
from django.db import transaction
from openai import APIError, RateLimitError

from ayudagente.radar.models import Event, Extraction, Observation, Requirement
from ayudagente.radar.services.extraction import Extractor
from ayudagente.radar.services.ingest import Ingested, Ingestor

logger = logging.getLogger(__name__)

RETRYABLE = (RateLimitError, APIError)  # retried by the task, never waited on inline


@shared_task(
    bind=True,
    autoretry_for=RETRYABLE,
    retry_backoff=True,
    retry_backoff_max=300,
    retry_jitter=True,
    max_retries=5,
    rate_limit="60/m",
)
def process_observation(self, observation_id: int, *, force: bool = False) -> dict:
    """
    Read one post and turn it into requirements.

    Args:
        observation_id (int): The post to process.
        force (bool): Re-extract even when a reading exists, to roll a new prompt over the
            corpus.

    Returns:
        dict: What was created and what was refused, so a caller can total a run without
            querying.

    Note:
        Safe to run twice. Extraction returns the stored reading, and ingest is skipped when
        the observation already produced requirements — otherwise a retry would duplicate
        every requirement the first attempt had already written.
    """
    observation = Observation.objects.select_related("event").get(pk=observation_id)

    if not force and Requirement.objects.filter(evidence=observation).exists():
        return {"observation": observation_id, "skipped": "already ingested"}

    extraction = Extractor().run(observation, force=force)
    outcome: Ingested = Ingestor().ingest(extraction)

    return {
        "observation": observation_id,
        "classification": extraction.classification,
        "requirements": len(outcome.requirements),
        "dropped": outcome.dropped,
    }


@shared_task
def process_event(event_id: int, *, limit: int | None = None, force: bool = False) -> dict:
    """
    Queue every post of an event that has not been read yet.

    Args:
        event_id (int): The event to process.
        limit (int | None): Cap on how many to queue, for a cheap first pass.
        force (bool): Re-read posts that already have an extraction.

    Returns:
        dict: How many were queued.
    """
    pending = pending_observations(event_id, force=force)
    if limit is not None:
        pending = pending[:limit]

    ids = list(pending.values_list("pk", flat=True))
    for observation_id in ids:
        process_observation.delay(observation_id, force=force)  # type: ignore[attr-defined]
    logger.info("queued %s observations for event %s", len(ids), event_id)
    return {"event": event_id, "queued": len(ids)}


def pending_observations(event_id: int, *, force: bool = False):
    """
    The posts of an event still waiting to be read.

    Args:
        event_id (int): The event.
        force (bool): When true, everything counts as pending.

    Returns:
        QuerySet[Observation]: Ordered oldest first, so a partial run covers the earliest
            part of the emergency rather than a random slice of it.
    """
    queryset = Observation.objects.filter(event_id=event_id).order_by("posted_at")
    if force:
        return queryset
    return queryset.filter(extraction__isnull=True)


@shared_task
def refresh_coverage(event_id: int) -> dict:
    """
    Repair the coverage cache from the matches a human acted on.

    Args:
        event_id (int): The event whose requirements to recompute.

    Returns:
        dict: How many rows were repaired.

    Note:
        `covered_quantity` is a cache, and a match that later fails leaves it overstating
        what is handled. An overstated cache is the dangerous direction: it makes a shortage
        look covered and stops the site being proposed.
    """
    event = Event.objects.get(pk=event_id)  # raises when the id is wrong, rather than no-op
    repaired = 0
    with transaction.atomic():
        for requirement in Requirement.objects.filter(event=event).select_for_update():
            before = requirement.covered_quantity
            requirement.recompute_covered_quantity()
            repaired += int(requirement.covered_quantity != before)
    return {"event": event_id, "repaired": repaired}


def unread_count(event_id: int) -> int:
    """
    How many posts of an event have never been read.

    Args:
        event_id (int): The event.

    Returns:
        int: Observations with no extraction.
    """
    return Observation.objects.filter(event_id=event_id, extraction__isnull=True).count()


def extraction_cost_estimate(event_id: int, count: int) -> tuple[int, int]:
    """
    Project the token spend of reading `count` more posts, from what reading cost so far.

    Args:
        event_id (int): The event to measure against.
        count (int): How many posts are about to be read.

    Returns:
        tuple[int, int]: Projected input and output tokens. Both zero until at least one
            observation has been read, because there is nothing to extrapolate from and a
            made-up number is worse than none.
    """
    done = Extraction.objects.filter(observation__event_id=event_id).exclude(input_tokens=0)
    sample = done.count()
    if not sample:
        return 0, 0
    totals = {"input": 0, "output": 0}
    for extraction in done.only("input_tokens", "output_tokens"):
        totals["input"] += extraction.input_tokens
        totals["output"] += extraction.output_tokens
    return (
        round(totals["input"] / sample * count),
        round(totals["output"] / sample * count),
    )
