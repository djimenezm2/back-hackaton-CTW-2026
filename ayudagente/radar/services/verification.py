"""
Deciding what a requirement is allowed to do before anything has confirmed it.

Nothing here waits for a person. A quarantine only a human can drain runs at the speed of
human review, which during an emergency is the scarcest resource there is and the one this
whole system exists to spend less of. So an unverified requirement is not held back until
someone looks — it is held back until the *world* corroborates it, and the world does that
by saying the same thing twice.

The question is never "is this true". It is **what may this be allowed to do**, and there are
three answers, in rising order of harm:

1. appear on the map — costs nothing when wrong
2. be matched against — costs a coordinator's attention
3. trigger a message to a real person — costs their trust, and ours

Quarantine forbids the second and third. It never hides anything: a coordinator looking at a
map should see that four unconfirmed needs were reported in a place, because that is itself a
reason to look.

Note:
    Needs and offers are not symmetric and the bar reflects it. A false need wastes a
    delivery. A false offer makes a real need look *covered*, so it stops being proposed and
    nobody notices — the failure is silent, which is the expensive direction.

    `text_image_conflict` quarantines on its own. The model flags it when a photo does not
    match what the text claims, which is the signature of recycled imagery, and no amount of
    follower count should override it.
"""

import logging

from ayudagente.radar.choices import Direction, RequirementStatus, precisions_at_least
from ayudagente.radar.models import Requirement
from ayudagente.radar.models.actors import ORGANIZATION_KINDS

logger = logging.getLogger(__name__)

# Corroboration: the same thing said by this many separate posts
CORROBORATING_POSTS = 2

# What an actor's own credibility has to reach to stand alone, per direction
TRUSTED_FOR_NEEDS = 0.60
TRUSTED_FOR_OFFERS = 0.75

# Below this a place cannot be acted on anyway, so it cannot leave quarantine
MIN_PRECISION = "admin_2"


def verdict(requirement: Requirement, *, evidence_count: int | None = None) -> tuple[bool, str]:
    """
    Decide whether a requirement may be acted on.

    Args:
        requirement (Requirement): The need or offer to judge.
        evidence_count (int | None): Supplied by callers that already counted, to keep a
            batch pass from issuing one query per row.

    Returns:
        tuple[bool, str]: Whether it clears the bar, and the reason either way. The reason is
            stored so a coordinator asking "why is this greyed out" gets an answer.
    """
    actor = requirement.actor

    if requirement.location is None or not _precise_enough(requirement):
        return False, f"location is only {requirement.location and requirement.location.precision}"

    extraction = _reading(requirement)
    if extraction is not None and extraction.text_image_conflict:
        return False, "the photo does not match what the text claims"

    count = evidence_count if evidence_count is not None else requirement.evidence.count()
    if count >= CORROBORATING_POSTS:
        return True, f"corroborated by {count} separate posts"

    if actor.verified:
        return True, "the platform verifies this account"

    floor = TRUSTED_FOR_OFFERS if requirement.direction == Direction.OFFERS else TRUSTED_FOR_NEEDS
    if actor.credibility >= floor:
        return (
            True,
            f"credibility {actor.credibility:.2f} clears the bar for {requirement.direction}",
        )

    if requirement.direction == Direction.NEEDS and actor.kind in ORGANIZATION_KINDS:
        return True, "reported by an organisation"

    return False, "a single post from an account nothing corroborates"


def apply(requirement: Requirement, *, evidence_count: int | None = None) -> bool:
    """
    Set a requirement's status from the verdict, and say whether it moved.

    Args:
        requirement (Requirement): The row to judge.
        evidence_count (int | None): Passed through to `verdict`.

    Returns:
        bool: True when the status changed.

    Note:
        Only ever moves between `open` and `unverified`. A requirement a human or the matching
        pass has already moved past those — covered, expired, discarded — is out of this
        function's hands, and quietly reopening one would undo a decision somebody made.
    """
    if requirement.status not in (RequirementStatus.OPEN, RequirementStatus.UNVERIFIED):
        return False

    cleared, reason = verdict(requirement, evidence_count=evidence_count)
    target = RequirementStatus.OPEN if cleared else RequirementStatus.UNVERIFIED
    if requirement.status == target:
        return False

    requirement.status = target
    requirement.save(update_fields=["status"])
    logger.info("requirement %s -> %s: %s", requirement.pk, target, reason)
    return True


def _precise_enough(requirement: Requirement) -> bool:
    """
    Whether the place is exact enough to act on.

    Note:
        A `country` point is the centroid of a nation. Matching already refuses it, so a
        requirement carrying one can never be acted on however credible its author — letting
        it out of quarantine would only put a pin on the map where nothing is.
    """
    return requirement.location.precision in precisions_at_least(MIN_PRECISION)


def _reading(requirement: Requirement):
    """The extraction behind this requirement, or None when the evidence is gone."""
    observation = requirement.evidence.first()
    return getattr(observation, "extraction", None) if observation else None
