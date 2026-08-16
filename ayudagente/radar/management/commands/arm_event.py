"""Give a proposed event permission to be harvested."""

from argparse import ArgumentParser

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from ayudagente.radar.choices import EventStatus
from ayudagente.radar.models import AdminUnit, Event
from ayudagente.radar.services.sweep import bootstrap_event


class Command(BaseCommand):
    """
    Arm a detected event: give it its search vocabulary, its watch targets and its sweep.

    Note:
        This is the one place a human decides to spend money, and it is deliberately a separate
        act from detecting. Detection is free and continuous; harvesting costs real credit per
        query, so the two must not be the same command.

        Even here nothing is scraped. The sweep is queued as pending jobs and `make harvest`
        runs them, so arming is reversible right up to the moment somebody dispatches.
    """

    help = "Activate a proposed event and queue its cold-start sweep."

    def add_arguments(self, parser: ArgumentParser) -> None:
        """Declare which event, and the vocabulary the feed could not know."""
        parser.add_argument("event_id", type=int)
        parser.add_argument("--languages", default="es", help="Comma separated ISO 639-1.")
        parser.add_argument("--hashtags", default="", help="Comma separated, without the #.")
        parser.add_argument(
            "--negatives", default="", help="Terms belonging to other concurrent emergencies."
        )
        parser.add_argument("--demand", default="", help="Words the affected write.")
        parser.add_argument("--supply", default="", help="Words helpers write.")

    def handle(self, *args, **options) -> None:
        """
        Activate the event and bootstrap its frontier.

        Raises:
            CommandError: When no such event exists, when it is already active, or when its
                country has no gazetteer — a sweep with no toponym pulls in other countries'
                disasters, which is invariant 9.
        """
        event = Event.objects.filter(pk=options["event_id"]).first()
        if event is None:
            raise CommandError(f"no event {options['event_id']}")
        if event.status == EventStatus.ACTIVE:
            raise CommandError(f"{event.name} is already active")
        if not AdminUnit.objects.filter(country_code=event.country_code).exists():
            raise CommandError(
                f"no gazetteer for {event.country_code}; run "
                f"`manage.py load_gazetteer {event.country_code}` first"
            )

        with transaction.atomic():
            event.languages = _terms(options["languages"])
            event.lexicon = {
                "hashtags": [f"#{t.lstrip('#')}" for t in _terms(options["hashtags"])],
                "negatives": _terms(options["negatives"]),
                "demand": _terms(options["demand"]),
                "supply": _terms(options["supply"]),
            }
            event.status = EventStatus.ACTIVE
            event.save(update_fields=["languages", "lexicon", "status"])
            counts = bootstrap_event(event)

        self.stdout.write(self.style.SUCCESS(f"armed {event} (id {event.pk})"))
        self.stdout.write(f"  {counts['nodes']} watch targets, {counts['jobs']} sweep jobs queued")
        self.stdout.write(f"\nrun them with:  make harvest ARGS='{event.pk}'")


def _terms(raw: str) -> list[str]:
    """Split a comma-separated option into clean terms."""
    return [term.strip() for term in raw.split(",") if term.strip()]
