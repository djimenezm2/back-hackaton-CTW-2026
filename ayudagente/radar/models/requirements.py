"""
Supply and demand, plus the links between them.

Needs and offers share one table because they share every field but polarity, and because
a single post routinely produces both: "we have plenty of food but no way to move it" is an
offer of food and a need for transport from the same actor.
"""

from django.db import models

from ayudagente.radar.choices import (
    Direction,
    MatchStatus,
    RequirementStatus,
    Urgency,
)

# Match states past which a recomputation must not touch the row: a human is already involved
FROZEN_MATCH_STATES = frozenset({
    MatchStatus.CONTACTED, MatchStatus.CONFIRMED, MatchStatus.DELIVERED,
})


class Requirement(models.Model):
    """
    One thing an actor needs or offers, at a place, within a time window.

    Unifying both directions in a single table makes matching a single query — opposite
    direction, compatible resource, nearby locations, overlapping windows — instead of two
    queries and a pile of special cases.

    Note:
        Transport is the case that justifies the shape: five trucks are one row with
        `resource=transport`, `quantity=5`, `location` as the origin and
        `destination` as the drop-off. Every other resource leaves `destination` null.

        `quantity` and `covered_quantity` are what make saturation work. When a center
        needs 20 volunteers and 10 are committed, the system stops proposing it once the
        total is reached. Without this it keeps pushing people toward a saturated site,
        which is the failure that does the most harm in a real emergency.

    See:
        `Match` for how two requirements get linked.
    """

    event = models.ForeignKey(
        'radar.Event', on_delete=models.CASCADE, related_name='requirements'
    )
    actor = models.ForeignKey(
        'radar.Actor', on_delete=models.CASCADE, related_name='requirements'
    )
    direction = models.CharField(max_length=10, choices=Direction.choices)

    resource = models.ForeignKey(
        'radar.ResourceType', on_delete=models.PROTECT, related_name='requirements'
    )
    free_text = models.CharField(max_length=300, blank=True)
    quantity = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    unit = models.CharField(max_length=30, blank=True)
    covered_quantity = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    location = models.ForeignKey(
        'radar.Location', on_delete=models.PROTECT, related_name='requirements'
    )
    destination = models.ForeignKey(
        'radar.Location', null=True, blank=True,
        on_delete=models.PROTECT, related_name='inbound_requirements',
    )

    window_start = models.DateTimeField(null=True, blank=True)
    window_end = models.DateTimeField(null=True, blank=True)
    urgency = models.CharField(
        max_length=10, choices=Urgency.choices, default=Urgency.MEDIUM
    )
    status = models.CharField(
        max_length=20, choices=RequirementStatus.choices, default=RequirementStatus.OPEN
    )

    confidence = models.FloatField(default=0.5)
    evidence = models.ManyToManyField(
        'radar.Observation', related_name='requirements'
    )

    created_at = models.DateTimeField(auto_now_add=True)
    last_seen_at = models.DateTimeField()

    class Meta:
        indexes = [
            models.Index(fields=['event', 'direction', 'resource', 'status']),
            models.Index(fields=['window_end']),  # drives the expiry sweep
            models.Index(fields=['status', 'urgency']),
        ]

    def __str__(self) -> str:
        return f'{self.actor.canonical_name} {self.direction} {self.resource.name}'

    @property
    def outstanding_quantity(self):
        """How much is still uncovered, or None when the amount was never stated."""
        if self.quantity is None:
            return None
        return max(self.quantity - self.covered_quantity, 0)

    @property
    def is_saturated(self) -> bool:
        """True when nothing more should be routed here."""
        if self.quantity is None:
            return self.status in (RequirementStatus.COVERED, RequirementStatus.EXPIRED)
        return self.covered_quantity >= self.quantity


class Match(models.Model):
    """
    A proposed or committed link between a need and an offer, optionally via transport.

    Matches are produced in batch by the matching pass, which loads the event's open
    requirements into an in-memory graph and solves an allocation problem over it. Postgres
    stays the source of truth; the graph is rebuilt and discarded each pass.

    Note:
        `via_transport` is what makes three-node chains work: food in Bogotá can satisfy a
        need in Cali only when a transport requirement links the two. Chains longer than
        that are a theoretical problem we do not have.

        Recomputation only rewrites rows still in `proposed`. Anything at `contacted` or
        beyond is frozen, because by then a real person has already been written to.
    """

    need = models.ForeignKey(
        Requirement, on_delete=models.CASCADE, related_name='matches_as_need'
    )
    offer = models.ForeignKey(
        Requirement, on_delete=models.CASCADE, related_name='matches_as_offer'
    )
    via_transport = models.ForeignKey(
        Requirement, null=True, blank=True,
        on_delete=models.SET_NULL, related_name='matches_as_transport',
    )

    committed_quantity = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True
    )
    distance_km = models.FloatField(null=True, blank=True)
    score = models.FloatField()
    rationale = models.TextField(blank=True)

    status = models.CharField(
        max_length=20, choices=MatchStatus.choices, default=MatchStatus.PROPOSED
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = 'matches'
        constraints = [
            models.UniqueConstraint(fields=['need', 'offer'], name='match_unique')
        ]
        indexes = [models.Index(fields=['status', '-score'])]

    def __str__(self) -> str:
        return f'{self.need_id} ← {self.offer_id} ({self.status})'

    @property
    def is_frozen(self) -> bool:
        """True when a human has already acted on this match and it must not be rewritten."""
        return self.status in FROZEN_MATCH_STATES
