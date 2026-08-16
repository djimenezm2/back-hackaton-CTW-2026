"""
Reading the replies under a post, which is where the affected actually write.

A live sweep produced 117 requirements of which 90% stayed in quarantine, and that number was
correct rather than a bad threshold. Toponym searches surface what ranks — press accounts and
aggregators reposting institutional announcements — so almost every requirement was a third
party reporting somebody else's need. Lowering the bar would only have let hearsay through.

The people asking for help are one level down. They reply to the announcement, they comment on
the video, they answer the collection point's post asking whether it is still open. That is
first-hand, it names a neighbourhood rather than a department, and it is the half of the
conversation a search never returns.

Note:
    Rule-driven, not agent-driven, and that follows from an invariant rather than convenience.
    Choosing which *post* to read replies under requires knowing what the post said, and the
    frontier agent never sees a post. So the agent allocates depth across places and accounts;
    this picks posts, mechanically, from what the pipeline already judged actionable.

    Only TikTok is wired. Its comment shape has a normalizer proven against 227 real rows from
    the pilot; the other three would each need one, and a comment stored through the wrong
    normalizer is worse than one not stored at all.
"""

import logging

from django.db.models import IntegerField, QuerySet
from django.db.models.functions import Cast, Coalesce

from ayudagente.radar.choices import (
    DecisionSource,
    ExtractionClass,
    HarvestTarget,
    JobStatus,
    Platform,
)
from ayudagente.radar.models import Event, HarvestJob, Observation
from ayudagente.radar.services.apify_inputs import COMMENT_ACTOR_BY_PLATFORM, build_comment_input

logger = logging.getLogger(__name__)

# Posts per job. The Actor takes several at once, so this is a batch, not a limit on depth.
POSTS_PER_JOB = 5

COMMENTS_PER_POST = 100

ACTIONABLE = (ExtractionClass.NEED, ExtractionClass.OFFER, ExtractionClass.BOTH)


def worth_reading(event: Event, platform: str) -> QuerySet:
    """
    The posts of one platform whose replies are most likely to hold first-hand reports.

    Args:
        event (Event): The emergency.
        platform (str): A `Platform` value.

    Returns:
        QuerySet[Observation]: Most engaged first, excluding posts already pulled and
            comments themselves.

    Note:
        Ranked by engagement, never filtered by it. A quiet post may still be the one person
        offering a truck, and refusing to read its replies to save a few cents is the kind of
        saving that costs the thing the system exists for. Order decides what is read first,
        not what is read at all.

        Replies are excluded as sources. Reading the replies of a reply is a thread walk, which
        is `HarvestTarget.THREAD` and a different decision.
    """
    already = HarvestJob.objects.filter(
        event=event, target_kind=HarvestTarget.COMMENTS, platform=platform
    ).values_list("actor_input__postURLs", flat=True)
    pulled = {url for batch in already if batch for url in batch}

    return (
        Observation.objects.filter(
            event=event,
            platform=platform,
            is_reply=False,
            extraction__classification__in=ACTIONABLE,
        )
        .exclude(permalink="")
        .exclude(permalink__in=pulled)
        .annotate(
            engagement=Coalesce(Cast("metrics__comments", IntegerField()), 0)
            + Coalesce(Cast("metrics__likes", IntegerField()), 0)
        )
        .order_by("-engagement")
    )


def queue_comment_pulls(event: Event, limit: int | None = None) -> int:
    """
    Queue a comment pull for the posts most likely to be worth one.

    Args:
        event (Event): The emergency.
        limit (int | None): Cap on jobs created this round.

    Returns:
        int: Jobs created. Zero when nothing new qualifies, which is the steady state once the
            engaged posts have all been read.

    Note:
        Only runs for platforms with a proven comments Actor, so this quietly does nothing for
        three of the four. That is deliberate — see the module note.
    """
    created = 0

    for platform in COMMENT_ACTOR_BY_PLATFORM:
        posts = list(worth_reading(event, platform)[:POSTS_PER_JOB])
        if not posts:
            continue
        if limit is not None and created >= limit:
            break

        permalinks = [post.permalink for post in posts]
        HarvestJob.objects.create(
            event=event,
            node=None,
            platform=platform,
            target_kind=HarvestTarget.COMMENTS,
            apify_actor=COMMENT_ACTOR_BY_PLATFORM[Platform(platform)],
            actor_input=build_comment_input(platform, permalinks, COMMENTS_PER_POST),
            decided_by=DecisionSource.RULE,
            rationale=(
                f"Replies under {len(posts)} engaged {platform} posts, where the affected "
                f"write. A search returns what ranks; the asking happens one level down."
            ),
            status=JobStatus.PENDING,
        )
        created += 1

    if created:
        logger.info("queued %s comment pulls for event %s", created, event.pk)
    return created
