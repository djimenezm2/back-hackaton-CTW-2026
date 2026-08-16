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
from ayudagente.radar.models import Event, HarvestJob, Media, Observation
from ayudagente.radar.seeds.base import Counts, Seed, Writer
from ayudagente.radar.services.normalize import normalize, parse_timestamp

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

    created = media_created = skipped = 0
    for item in items:
        fields, media_specs = normalize(
            spec["platform"], item, is_comment=spec.get("is_comment", False)
        )
        if not fields.get("platform_id") or not fields.get("posted_at"):
            skipped += 1
            continue

        observation, was_created = Observation.objects.get_or_create(
            platform=spec["platform"],
            platform_id=fields["platform_id"],
            defaults={**fields, "event": event, "job": job, "raw": item},
        )
        if not was_created:
            continue
        created += 1

        # These source URLs expired long ago; the alt text beside them is still usable
        Media.objects.bulk_create(Media(observation=observation, **media) for media in media_specs)
        media_created += len(media_specs)

    if created:
        job.items_new = created
        job.save(update_fields=["items_new"])
    write(
        f"  {spec['file']:<26} {created:>4} observations, "
        f"{media_created:>4} media, {skipped:>3} skipped"
    )
    return {"observations": created, "media": media_created, "skipped": skipped}


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
