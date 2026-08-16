"""
`get_actor_contacts` as an agent tool.

The one rule that shapes it: the model never sees the phone number or the email address.
It gets the channel, how confident we are and how to refer to it, and that is enough to
decide which channel to use. `draft_outreach` takes the id and reads the value itself.

Note:
    Keeping the value out of the context window is the cheapest privacy control available.
    A phone number that never enters a prompt cannot be echoed into a message body, logged
    by a provider, or recalled into an unrelated answer.
"""

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from agent_tools.shared import failure
from ayudagente.radar.services import get_actor, get_contact_points


class GetActorContactsInput(BaseModel):
    """Arguments for `get_actor_contacts`."""

    actor_id: int = Field(
        description="Actor to look up, as returned in `actor_id` by find_requirements."
    )
    include_unusable: bool = Field(
        default=False,
        description=(
            "Also list details that cannot carry a message, such as payment accounts. "
            "Useful to answer 'how can I donate to them', not to write to them."
        ),
    )


def serialize(contact) -> dict:
    """
    Describe a channel without revealing it.

    Returns:
        dict: `contact_point_id` is what other tools accept; `value` is deliberately absent.
    """
    row = {
        "contact_point_id": contact.id,
        "kind": contact.kind,
        "reachable": contact.reachable,
        "verified": contact.verified,
        "times_seen": contact.times_seen,
        "confidence": round(contact.confidence, 2),
        "can_carry_a_message": contact.can_carry_a_message,
        "preference_rank": contact.preference_rank(),
    }
    if contact.platform:
        row["platform"] = contact.platform
    if contact.payment_network:
        row["payment_network"] = contact.payment_network
    if contact.unreachable_reason:
        row["unreachable_reason"] = contact.unreachable_reason
    return row


@tool("get_actor_contacts", args_schema=GetActorContactsInput)
def get_actor_contacts(actor_id: int, include_unusable: bool = False) -> dict:
    """
    List the ways to reach an actor, best channel first.

    Call this before drafting a message, to pick a channel and to learn whether one exists
    at all — plenty of posts name a place without naming any way to contact it.

    Contact values are never returned. Use `contact_point_id` with `draft_outreach`, which
    reads the address itself. `preference_rank` orders least intrusive first; the first row
    is the one to use unless you have a reason not to.

    An actor merged into another resolves to the surviving one, so the contacts and the
    outreach history stay together.
    """
    actor = get_actor(actor_id)
    if actor is None:
        return failure(f"actor {actor_id} does not exist", contacts=[])

    contacts = get_contact_points(actor, usable_only=not include_unusable)

    return {
        "actor_id": actor.id,
        "actor": actor.canonical_name,
        "actor_kind": actor.kind,
        "is_organization": actor.is_organization,
        "count": len(contacts),
        "contacts": [serialize(c) for c in contacts],
    }
