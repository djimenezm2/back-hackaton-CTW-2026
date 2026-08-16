"""
The real harvest: 939 raw items from the Chocó earthquake, committed under `data/pilot/`.

This is the corpus the extraction, geocoding, identity and matching work is developed
against, and the regression set for prompt changes — re-scraping would give a different one
every time.
"""

import gzip
import json
from collections import Counter
from pathlib import Path

from django.conf import settings
from django.contrib.gis.geos import Point

from ayudagente.radar.choices import DecisionSource, JobStatus
from ayudagente.radar.models import Event, HarvestJob
from ayudagente.radar.seeds.base import Counts, Seed, Writer
from ayudagente.radar.services.harvest import persist_items
from ayudagente.radar.services.normalize import parse_timestamp

PILOT_DIR = Path(settings.BASE_DIR) / "data" / "pilot"


def _load_event(spec: dict, write: Writer) -> Event:
    """
    Create the event the harvest hangs off, or reuse it.

    Args:
        spec (dict): The `event` block of the manifest.
        write (Writer): Progress sink.

    Returns:
        Event: The pilot event, matched by name so a second run reuses it.
    """
    longitude, latitude = spec["epicenter"]
    event, created = Event.objects.get_or_create(
        name=spec["name"],
        defaults={
            "hazard": spec["hazard"],
            "occurred_at": parse_timestamp(spec["occurred_at"]),
            "epicenter": Point(longitude, latitude, srid=4326),
            "magnitude": spec["magnitude"],
            "depth_km": spec["depth_km"],
            "country_code": spec["country_code"],
            "languages": spec["languages"],
            "detection_source": spec["detection_source"],
            "lexicon": spec["lexicon"],
        },
    )
    write(f"  {'created' if created else 'reusing'} event: {event}")
    return event


def _load_file(base: Path, spec: dict, event: Event, write: Writer) -> Counts:
    """
    Load one payload file, recording the job it came from.

    Args:
        base (Path): Directory holding the manifest and payloads.
        spec (dict): One entry of the manifest's `files` list.
        event (Event): Event the observations belong to.
        write (Writer): Progress sink.

    Returns:
        Counts: Observations and media created, plus items skipped.

    Note:
        Skipped items lacked an id or a timestamp, both of which `Observation` requires.
        Duplicates are not skipped but silently reused: the same post is often returned by
        two different queries, and the uniqueness constraint collapses them.
    """
    with gzip.open(base / spec["file"], "rt", encoding="utf-8") as handle:
        items = json.load(handle)

    job, _ = HarvestJob.objects.get_or_create(
        event=event,
        dataset_id=spec["dataset_id"],
        defaults={
            "platform": spec["platform"],
            "apify_actor": spec["apify_actor"],
            "actor_input": {"seeded_from": spec["dataset_id"], "note": spec.get("note", "")},
            "decided_by": DecisionSource.MANUAL,
            "rationale": f"Seeded from the pilot harvest: {spec.get('note', '')}",
            "status": JobStatus.DONE,
            "items_returned": len(items),
            "actual_cost_usd": spec.get("cost_usd", 0),
        },
    )

    # The same writer the live harvest uses, so a replayed post and a fetched one are equal
    result = persist_items(job, items, is_comment=spec.get("is_comment", False))

    if result.items_new:
        job.items_new = result.items_new
        job.save(update_fields=["items_new"])
    write(
        f"  {spec['file']:<26} {result.items_new:>4} observations, "
        f"{result.media:>4} media, {result.skipped:>3} skipped"
    )
    return {
        "observations": result.items_new,
        "media": result.media,
        "skipped": result.skipped,
    }


def load(write: Writer) -> Counts:
    """
    Load the committed harvest.

    Args:
        write (Writer): Progress sink.

    Returns:
        Counts: What was created, zero everywhere on a second run.

    Raises:
        FileNotFoundError: If `data/pilot/manifest.json` is missing.
    """
    manifest = json.loads((PILOT_DIR / "manifest.json").read_text())
    event = _load_event(manifest["event"], write)

    totals: Counter[str] = Counter()
    for spec in manifest["files"]:
        totals.update(_load_file(PILOT_DIR, spec, event, write))
    return dict(totals)


SEED = Seed(
    name="pilot",
    description="939 real items harvested from the Chocó earthquake (M7.4, 10 Aug 2026)",
    event_names=("Chocó earthquake M7.4",),
    load=load,
)
