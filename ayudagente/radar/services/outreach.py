"""
Drafting outreach: the only door from proposals to a real person's inbox.

The policy is the model's `allows_automatic_outreach()` and it fails closed — this module
never widens it. Everything lands as DRAFT; the `automatic` flag only marks messages that
*may* skip human review, it does not send anything.
"""

from ayudagente.radar.choices import ContactKind, OutreachChannel
from ayudagente.radar.models import ContactPoint, Match, Outreach

CHANNEL_BY_CONTACT_KIND = {
    ContactKind.EMAIL: OutreachChannel.EMAIL,
    ContactKind.WHATSAPP: OutreachChannel.WHATSAPP,
    ContactKind.PHONE: OutreachChannel.PHONE_CALL,
    ContactKind.HANDLE: OutreachChannel.DIRECT_MESSAGE,
}


def draft_outreach(
    match: Match | None,
    contact_point: ContactPoint,
    body: str,
    subject: str = '',
    drafted_by: str = 'agent',
) -> Outreach:
    """
    Create (idempotently) a draft message to the contact point's actor about a match.

    Retries return the existing row instead of writing twice — the idempotency key is
    what keeps "ten people already contacted" true rather than approximately true.
    """
    channel = CHANNEL_BY_CONTACT_KIND.get(contact_point.kind)
    if channel is None:
        raise ValueError(
            f'contact kind {contact_point.kind!r} is not a messaging channel'
        )

    key = Outreach.build_idempotency_key(
        contact_point.actor_id, match.id if match else None, channel
    )
    outreach, _created = Outreach.objects.get_or_create(
        idempotency_key=key,
        defaults={
            'match': match,
            'target_actor_id': contact_point.actor_id,
            'contact_point': contact_point,
            'channel': channel,
            'subject': subject,
            'body': body,
            'drafted_by': drafted_by,
            'automatic': contact_point.allows_automatic_outreach(),
        },
    )
    return outreach
