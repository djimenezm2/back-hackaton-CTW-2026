"""The persisted graph: what the frontend reads, rebuilt only when its inputs change."""

from django.db import models


class GraphSnapshot(models.Model):
    """
    The event's graph, serialized once and served as-is.

    Recomputing the graph on every fetch wastes the exact same work a hundred times when
    nothing changed. The snapshot inverts it: writes (new requirements, agent actions,
    match updates) trigger a rebuild through signals, and reads are a single row.

    Note:
        `input_fingerprint` is what makes the trigger cheap to over-fire. It hashes the
        graph's inputs, so a rebuild request that finds the stored fingerprint unchanged
        does nothing. Fifty redundant triggers cost fifty hash comparisons, not fifty
        matching passes — and the matches the pass itself writes are part of the stored
        fingerprint, which is what terminates the write→trigger→write loop.
    """

    event = models.OneToOneField(
        "radar.Event", on_delete=models.CASCADE, related_name="graph_snapshot"
    )
    payload = models.JSONField()
    input_fingerprint = models.CharField(max_length=64)
    built_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"graph snapshot #{self.pk} @ {self.built_at:%H:%M:%S}"
