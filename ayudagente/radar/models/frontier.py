"""The scoreboard the frontier agent reads, and nothing else."""

from django.db import models

from ayudagente.radar.choices import NodeStatus, Platform, Ring, Zone


class FrontierNode(models.Model):
    """
    One searchable cell — a municipality on a platform — with its running performance.

    This is the only table the agent ever reads. Around fifty rows, roughly two thousand
    tokens, and it never sees a single post. Reading a scoreboard and deciding where to
    spend under uncertainty is judgment, which is what the model is good at; extracting a
    phone number from a caption is a function, which it is not.

    Note:
        `score` divides by cost on purpose. Without that divisor the agent burns the budget
        on expensive platforms that look productive per item but are not per dollar.

        `last_useful_find_at` drives the freshness decay: a node that has been quiet for
        hours falls on its own without anyone deciding to demote it.

        A share of the budget must always go to nodes with no history at all. Without
        forced exploration the agent converges onto what it already knows and never finds
        the rural district nobody was posting about twenty minutes ago — precisely the case
        with the highest value.
    """

    event = models.ForeignKey(
        'radar.Event', on_delete=models.CASCADE, related_name='frontier'
    )
    admin_unit = models.ForeignKey(
        'radar.AdminUnit', on_delete=models.PROTECT, related_name='frontier_nodes'
    )
    platform = models.CharField(max_length=20, choices=Platform.choices)
    ring = models.CharField(max_length=4, choices=Ring.choices)
    zone = models.CharField(max_length=10, choices=Zone.choices)

    yield_rate = models.FloatField(default=0)  # actionable items per 100 harvested
    avg_credibility = models.FloatField(default=0.5)
    distance_km = models.FloatField(null=True, blank=True)
    freshness = models.FloatField(default=1.0)
    avg_cost_usd = models.DecimalField(max_digits=8, decimal_places=6, default=0)
    score = models.FloatField(default=0, db_index=True)

    cadence_minutes = models.IntegerField(default=60)
    last_harvest_at = models.DateTimeField(null=True, blank=True)
    last_useful_find_at = models.DateTimeField(null=True, blank=True)

    passes = models.IntegerField(default=0)
    total_items = models.IntegerField(default=0)
    actionable_items = models.IntegerField(default=0)
    total_cost_usd = models.DecimalField(max_digits=8, decimal_places=4, default=0)

    status = models.CharField(
        max_length=20, choices=NodeStatus.choices, default=NodeStatus.ACTIVE
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['event', 'admin_unit', 'platform'], name='frontier_node_unique'
            )
        ]
        indexes = [models.Index(fields=['event', 'status', '-score'])]

    def __str__(self) -> str:
        return f'{self.admin_unit.name} · {self.platform} · {self.ring}'

    @property
    def is_unexplored(self) -> bool:
        """True when this node has never been harvested and has no history to score."""
        return self.passes == 0

    def cost_per_actionable_usd(self):
        """
        Cost of one actionable item at this node, or None before anything was found.

        Returns:
            Decimal | None: Total spend divided by actionable items found so far.
        """
        if not self.actionable_items:
            return None
        return self.total_cost_usd / self.actionable_items
