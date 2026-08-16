"""
The triggers that keep the stored graph current.

Any write to the graph's inputs — actors, requirements, matches, whether from ingestion,
an agent tool or the admin — queues a rebuild after the transaction commits. The rebuild
itself is fingerprint-guarded, so redundant triggers are cheap by design; the one trigger
worth suppressing is the write storm the matching pass causes while a rebuild is already
running, which is what the `rebuilding` flag does.
"""

import logging

from django.db import transaction
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from ayudagente.radar.models import Actor, Match, Requirement
from ayudagente.radar.services.graph import rebuilding

logger = logging.getLogger(__name__)


def _schedule_rebuild(event_id: int | None) -> None:
    if event_id is None or rebuilding.get():
        return

    def enqueue() -> None:
        from ayudagente.radar.tasks import rebuild_graph

        try:
            rebuild_graph.delay(event_id)  # type: ignore[attr-defined]  # celery stubs
        except Exception:  # broker down (local shell without redis) — reads self-heal
            logger.warning("could not queue graph rebuild for event %s", event_id)

    transaction.on_commit(enqueue)


@receiver(post_save, sender=Actor)
@receiver(post_delete, sender=Actor)
@receiver(post_save, sender=Requirement)
@receiver(post_delete, sender=Requirement)
def _on_node_change(sender, instance, **kwargs):
    _schedule_rebuild(instance.event_id)


@receiver(post_save, sender=Match)
@receiver(post_delete, sender=Match)
def _on_edge_change(sender, instance, **kwargs):
    event_id = (
        Requirement.objects.filter(id=instance.need_id).values_list("event_id", flat=True).first()
    )
    _schedule_rebuild(event_id)
