"""Stable catalogs: administrative geography and the resource taxonomy."""

from django.contrib.gis.db import models as gis
from django.db import models

from ayudagente.radar.choices import AdminLevel


class AdminUnit(models.Model):
    """
    An official administrative division of the country (Colombia's DIVIPOLA).

    Loaded once and shared by every event. It is the backbone of geographic scoping: the
    agent widens its search by walking real entities instead of inventing place names, and
    every frontier node points at one of these.

    Note:
        The hierarchy is department → municipality → settlement, via `parent`. The
        `centroid` lets us rank municipalities by distance to the epicenter to build the
        cadence rings without geocoding anything.

    See:
        `ayudagente.radar.models.frontier.FrontierNode`,
        `ayudagente.radar.models.actors.Location`.
    """

    code = models.CharField(max_length=8, unique=True)
    name = models.CharField(max_length=120)
    name_norm = models.CharField(max_length=120, db_index=True)  # unaccented, lowercased
    level = models.CharField(max_length=20, choices=AdminLevel.choices)
    parent = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.PROTECT, related_name="children"
    )
    centroid = gis.PointField(geography=True, null=True, blank=True)
    population = models.IntegerField(null=True, blank=True)

    class Meta:
        indexes = [models.Index(fields=["level", "name_norm"])]

    def __str__(self) -> str:
        return f"{self.name} ({self.get_level_display()})"


class ResourceType(models.Model):
    """
    Hierarchical taxonomy of what people need and offer.

    It is a table rather than an enum so resources can be added mid-emergency without a
    migration. The hierarchy allows matching by category when there is no exact match: a
    need for "sleeping mats" can be met by an offer of "bedding" when nothing closer exists.

    Note:
        `perishable` constrains transport matching — a perishable resource requires a
        short delivery window.
    """

    key = models.SlugField(max_length=60, unique=True)
    name = models.CharField(max_length=120)
    parent = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.PROTECT, related_name="children"
    )
    default_unit = models.CharField(max_length=30, blank=True)
    perishable = models.BooleanField(default=False)

    def __str__(self) -> str:
        return self.name

    def ancestors(self) -> list["ResourceType"]:
        """
        Return the chain of parent categories, nearest first.

        Returns:
            list[ResourceType]: Ancestors in order; empty when this is a root resource.
        """
        chain, current = [], self.parent
        while current is not None:
            chain.append(current)
            current = current.parent
        return chain
