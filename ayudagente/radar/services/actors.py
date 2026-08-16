"""
Reading actors and the ways to reach them.

Choosing a channel is a policy, not a preference: `ContactPoint.preference_rank` decides
what a human gets offered first, and this module only orders and filters by it. Nothing
here sends anything, and nothing here widens what counts as reachable.
"""

from ayudagente.radar.models import Actor, ContactPoint


def get_actor(actor_id: int) -> Actor | None:
    """
    Fetch an actor, following a merge when one happened.

    Returns:
        Actor | None: The canonical actor. A merged duplicate resolves to the row that
            absorbed it, because acting on the duplicate would split the outreach history
            that saturation counting depends on.
    """
    actor = Actor.objects.select_related("merged_into", "location").filter(id=actor_id).first()
    if actor is not None and actor.merged_into_id is not None:
        return Actor.objects.select_related("location").filter(id=actor.merged_into_id).first()
    return actor


def get_contact_points(actor: Actor, usable_only: bool = True) -> list[ContactPoint]:
    """
    Every way to reach an actor, best channel first.

    Args:
        actor (Actor): Whose contacts to list.
        usable_only (bool): Drop details that cannot carry a message — a payment account is
            a way to give someone money, not a way to talk to them.

    Returns:
        list[ContactPoint]: Ordered by `preference_rank`, then by how often the detail was
            seen. A number appearing in five posts is more likely real than one appearing
            once, and that is the tiebreak worth having.
    """
    contacts = list(ContactPoint.objects.filter(actor=actor))
    if usable_only:
        contacts = [c for c in contacts if c.can_carry_a_message]
    return sorted(contacts, key=lambda c: (c.preference_rank(), -c.times_seen, -c.confidence))


def best_contact_point(actor: Actor) -> ContactPoint | None:
    """
    The single channel to offer first for this actor.

    Returns:
        ContactPoint | None: None when nothing usable exists, which is a real and common
            state — plenty of posts name a place without naming a way to reach it.
    """
    contacts = get_contact_points(actor)
    return contacts[0] if contacts else None
