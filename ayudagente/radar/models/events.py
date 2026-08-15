"""The event: the isolation boundary for the whole system."""

from django.contrib.gis.db import models as gis
from django.db import models

from ayudagente.radar.choices import EventStatus, HazardKind
from ayudagente.radar.models.catalog import AdminUnit


class Event(models.Model):
    """
    One concrete disaster, with its official ground truth and its budget.

    Almost the entire graph hangs off an event: actors, requirements and frontier nodes
    belong to exactly one and never mix across events. Two simultaneous emergencies mean
    two independent agents, two budgets and two frontiers, sharing nothing but the
    geographic catalog.

    Note:
        `lexicon` stores how people actually refer to the event — hashtags, nicknames, the
        name of the building that collapsed — and, under `negatives`, the terms belonging
        to other concurrent emergencies so they can be excluded from queries. That
        exclusion is the cheapest defense against conflating two different earthquakes.

    See:
        `ayudagente.radar.models.frontier.FrontierNode` for the search state.
    """

    hazard = models.CharField(max_length=20, choices=HazardKind.choices)
    name = models.CharField(max_length=200)
    occurred_at = models.DateTimeField()
    epicenter = gis.PointField(geography=True, null=True, blank=True)
    magnitude = models.FloatField(null=True, blank=True)
    depth_km = models.FloatField(null=True, blank=True)

    detection_source = models.CharField(max_length=40)  # gdacs|usgs|emsc|sgc|manual
    external_id = models.CharField(max_length=80, blank=True)

    affected_units = models.ManyToManyField(AdminUnit, blank=True, related_name="events")
    lexicon = models.JSONField(default=dict)  # {hashtags: [], nicknames: [], negatives: []}

    status = models.CharField(
        max_length=20, choices=EventStatus.choices, default=EventStatus.ACTIVE
    )
    budget_usd = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    spent_usd = models.DecimalField(max_digits=8, decimal_places=4, default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [models.Index(fields=["status", "occurred_at"])]

    def __str__(self) -> str:
        return f"{self.name} ({self.occurred_at:%Y-%m-%d})"

    @property
    def remaining_budget_usd(self):
        """Budget still available for harvesting, never negative."""
        return max(self.budget_usd - self.spent_usd, 0)

    def can_spend(self, amount_usd) -> bool:
        """
        Report whether a harvest job of a given cost is affordable.

        Args:
            amount_usd (Decimal): Estimated cost of the job.

        Returns:
            bool: True when the event is active and the amount fits the remaining budget.
        """
        return self.status == EventStatus.ACTIVE and amount_usd <= self.remaining_budget_usd
