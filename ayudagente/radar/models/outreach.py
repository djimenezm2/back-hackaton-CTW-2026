"""The action surface: turning a match into a message someone actually receives."""

import hashlib

from django.conf import settings
from django.db import models

from ayudagente.radar.choices import OutreachChannel, OutreachStatus


class Outreach(models.Model):
    """
    One message to one actor about one match, from draft through to reply.

    This is where the system stops observing and starts intervening, so it carries the
    strictest guarantees in the codebase. Everything is recorded: who was written to, on
    which channel, drafted by which model, approved by which person.

    Note:
        `idempotency_key` is what keeps saturation counting honest. A Celery task can be
        retried three times, but the unique constraint means the message is only ever
        created once, so "ten people already contacted" stays true.

        `automatic` is False by default and may only be set by
        `ContactPoint.allows_automatic_outreach`, which permits email to organizations and
        nothing else.

    See:
        `ayudagente.radar.models.actors.ContactPoint` for the policy.
    """

    match = models.ForeignKey(
        'radar.Match', null=True, blank=True,
        on_delete=models.SET_NULL, related_name='outreach',
    )
    target_actor = models.ForeignKey(
        'radar.Actor', on_delete=models.CASCADE, related_name='received_outreach'
    )
    contact_point = models.ForeignKey(
        'radar.ContactPoint', on_delete=models.PROTECT, related_name='messages'
    )
    channel = models.CharField(max_length=20, choices=OutreachChannel.choices)

    subject = models.CharField(max_length=200, blank=True)
    body = models.TextField()
    drafted_by = models.CharField(max_length=80)  # Azure deployment that wrote it

    status = models.CharField(
        max_length=20, choices=OutreachStatus.choices, default=OutreachStatus.DRAFT
    )
    automatic = models.BooleanField(default=False)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name='approved_outreach',
    )
    sent_at = models.DateTimeField(null=True, blank=True)
    reply_text = models.TextField(blank=True)
    replied_at = models.DateTimeField(null=True, blank=True)
    error = models.TextField(blank=True)

    idempotency_key = models.CharField(max_length=64, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name_plural = 'outreach'
        indexes = [models.Index(fields=['status', 'created_at'])]

    def __str__(self) -> str:
        return f'{self.channel} → {self.target_actor_id} ({self.status})'

    @staticmethod
    def build_idempotency_key(actor_id: int, match_id: int | None, channel: str) -> str:
        """
        Build the key that prevents contacting the same actor twice about the same match.

        Args:
            actor_id (int): Recipient actor.
            match_id (int | None): Match being acted on, or None for a general message.
            channel (str): An `OutreachChannel` value.

        Returns:
            str: Hex SHA-256 digest, stable across retries of the same task.
        """
        return hashlib.sha256(f'{actor_id}|{match_id or ""}|{channel}'.encode()).hexdigest()
