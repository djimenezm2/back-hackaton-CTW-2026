"""
The one multimodal call that turns an observation into structured meaning.

Everything a post can tell us comes out of a single schema-constrained request: what it is,
what is needed or offered, what the picture shows, and the string to geocode. Splitting it
into four calls would cost four times the rate limit for the same work, and would lose the
one thing a combined call has — seeing the caption and the image together, which is what
catches a photo that does not match its text.
"""

import base64
import mimetypes
from pathlib import Path
from typing import Any

from django.conf import settings
from django.utils import timezone

from ayudagente.radar.choices import ExtractionClass
from ayudagente.radar.llm import Role, client, model_for
from ayudagente.radar.models import Extraction, Media, Observation
from ayudagente.radar.schemas import ExtractionResult

PROMPT_VERSION = "v4"

SYSTEM_PROMPT = """\
You read one social media post from a disaster zone and return structured facts.

You are looking for two things and only two:
- DEMAND: someone who needs something concrete — water, food, medicine, shelter, transport,
  rescue, volunteers — at a place.
- SUPPLY: someone offering something concrete — a collection point, a vehicle, a donation
  drive, volunteers, a company giving goods.

Rules that matter more than completeness:

1. Never invent a place, a quantity or a contact. If the post does not say it, leave it empty.
   An approximate collection point is worse than no collection point: it sends people to the
   wrong address during an emergency.

2. One post can hold several items. A post listing three collection centers is three items.
   "We have food but no way to move it" is two items with opposite directions from one actor.

3. Direction follows what the actor does with the resource, not their role. An authority
   asking for help NEEDS it; coordinating a response is not offering. Only emit `offers` when
   the actor is putting something concrete in — goods, a vehicle, a place, their own hands.
   Never emit both directions for the same resource and actor.

4. Capture every number that quantifies a need or an offer, with its unit as written. Both
   "500 litros de agua" and "80 familias afectadas" are quantities; the first counts the
   resource and the second the people, and the unit is what tells them apart. Leave it empty
   only when the post gives no number at all.

5. Use one exact name per entity throughout the post. If the mayor's office appears as
   "Alcaldía de Herveo", never also call it "administración municipal": one entity written
   three ways becomes three entities downstream.

6. Only report contacts written in the post itself. The author's own handle is already known
   and must never be repeated as a contact — a phone, an email or an account is a contact
   only when someone wrote it down.

7. A need or an offer exists only when someone states it. Describing damage is not asking
   for help: an article saying a family's house collapsed reports a fact, and inferring that
   they need transport and volunteers invents demand nobody requested. Emit an item only for
   what the post actually asks for or actually puts on the table.

8. Classify as `discard` anything left with nothing to act on — argument about how the
   response is being handled, and reporting that describes the disaster without anyone
   asking for or offering something.

9. Set `belongs_to_event` to false when the post is about a different disaster. Several
   emergencies share vocabulary and language; the event context below tells you which is ours.

10. Read the images. Flyers carry the address, the hours and the phone that the caption omits.
   Put what you can read into `visual_summary`, and use it to fill the item fields too.

11. Build `geocode_query` as one line a geocoder could resolve, appending the event's country.
   Use the finest place the post names — a neighborhood or rural district beats a city.
"""

EVENT_CONTEXT = """\
Event: {name} ({hazard}, magnitude {magnitude}) on {occurred_at:%Y-%m-%d} in {country}.
Languages expected: {languages}.
Other concurrent disasters that must NOT be confused with this one: {negatives}.
"""


class Extractor:
    """
    Runs the multimodal pass and persists the result.

    Note:
        The `Extraction` row is written the moment the model answers, before geocoding or
        identity resolution run. That is deliberate: a retry after a failure further down the
        pipeline must not pay for the model call twice, and `run` returning the existing row
        is what makes the surrounding task safe to retry.
    """

    def __init__(self, prompt_version: str = PROMPT_VERSION, model: str | None = None):
        self.prompt_version = prompt_version
        self.model = model or model_for(Role.EXTRACTION)

    def run(self, observation: Observation, *, force: bool = False) -> Extraction:
        """
        Extract one observation, reusing the stored result unless asked not to.

        Args:
            observation (Observation): The post to read.
            force (bool): Re-run even when an extraction already exists, which is how a
                changed prompt is rolled out over the corpus.

        Returns:
            Extraction: The stored interpretation.

        Raises:
            ValueError: If the model refused or returned nothing parseable, so the caller
                can retry rather than persist an empty reading.
        """
        existing = Extraction.objects.filter(observation=observation).first()
        if existing and not force:
            return existing

        response = client().responses.parse(
            model=self.model,
            input=self.build_input(observation),
            text_format=ExtractionResult,
        )
        result = response.output_parsed
        if result is None:
            raise ValueError(f"no parseable output for observation {observation.pk}")
        self._repair(result, observation)
        return self._persist(observation, result, replacing=existing, usage=response.usage)

    def build_input(self, observation: Observation) -> list[Any]:
        """
        Assemble the instructions, the event context and the post itself.

        Args:
            observation (Observation): The post to read.

        Returns:
            list[Any]: Responses API input blocks, with `input_image` entries appended for
                whatever media still resolves.
        """
        content: list[Any] = [
            {"type": "input_text", "text": self._event_context(observation)},
            {"type": "input_text", "text": self._render(observation)},
        ]
        content.extend(self._image_blocks(observation))
        return [
            {"role": "system", "content": [{"type": "input_text", "text": SYSTEM_PROMPT}]},
            {"role": "user", "content": content},
        ]

    def _repair(self, result: ExtractionResult, observation: Observation) -> None:
        """
        Fill in what the model cannot know but the observation already does.

        Args:
            result (ExtractionResult): Parsed output, edited in place.
            observation (Observation): The post it came from.

        Note:
            Measured across model tiers rather than assumed: every tier leaves the actor
            unnamed or paraphrased when the author is the subject, which is exactly the case
            where the handle is already known. Asking the model for it buys nothing and
            invites several spellings of one entity.

            Contradictory directions from one actor are *not* repaired here. Spotting them
            needs the actor resolved first, and inside a single extraction the names have
            already drifted — so that check belongs after identity resolution.
        """
        author = observation.author_handle or observation.author_name
        for item in result.items:
            if author and not item.actor.name.strip():
                item.actor.name = author

    def _event_context(self, observation: Observation) -> str:
        """Tell the model which disaster is ours, and which ones share its vocabulary."""
        event = observation.event
        lexicon = event.lexicon or {}
        return EVENT_CONTEXT.format(
            name=event.name,
            hazard=event.get_hazard_display(),
            magnitude=event.magnitude or "unknown",
            occurred_at=event.occurred_at,
            country=event.country_code,
            languages=", ".join(event.languages) or "any",
            negatives=", ".join(lexicon.get("negatives", [])) or "none known",
        )

    def _render(self, observation: Observation) -> str:
        """Lay out everything the platform gave us as text, skipping what it did not."""
        parts = [
            f"Platform: {observation.platform}",
            f"Posted at: {observation.posted_at:%Y-%m-%d %H:%M} UTC",
            f"Author: @{observation.author_handle or observation.author_name or 'unknown'}",
            f"Text: {observation.text or '(none)'}",
        ]
        if observation.transcript:
            parts.append(f"Spoken transcript: {observation.transcript}")
        if observation.platform_geo_name:
            parts.append(f"Platform location tag: {observation.platform_geo_name}")

        # Facebook ships its own OCR of the attached image, which often carries the flyer
        alt_texts = [
            media.platform_alt_text
            for media in Media.objects.filter(observation=observation)
            if media.platform_alt_text
        ]
        if alt_texts:
            parts.append("Platform image descriptions: " + " | ".join(alt_texts))
        return "\n".join(parts)

    def _image_blocks(self, observation: Observation) -> list[Any]:
        """
        Build image inputs from our own stored copies, inlined as data URIs.

        Returns:
            list[Any]: `input_image` blocks, empty when nothing is readable.

        Note:
            The bytes travel in the request rather than as a link. A path under `MEDIA_ROOT`
            is not reachable from OpenAI's side, and the platform URL beside it expired hours
            after the harvest, so inlining is the only thing that works for both.

            Seeded pilot observations therefore go through as text only — correct rather than
            a failure, since their images no longer exist anywhere.
        """
        blocks = []
        for media in Media.objects.filter(observation=observation):
            data_uri = self._as_data_uri(media.blob_path)
            if data_uri:
                blocks.append({"type": "input_image", "image_url": data_uri})
        return blocks

    def _as_data_uri(self, blob_path: str) -> str:
        """
        Read a stored image and encode it for transport.

        Args:
            blob_path (str): Path relative to `MEDIA_ROOT`.

        Returns:
            str: A `data:` URI, or an empty string when the file is missing. A missing file
                is skipped rather than raised on, because one unreadable image should not
                cost the whole extraction.
        """
        if not blob_path:
            return ""
        path = Path(settings.MEDIA_ROOT) / blob_path
        if not path.is_file():
            return ""
        mime = mimetypes.guess_type(path.name)[0] or "image/jpeg"
        payload = base64.b64encode(path.read_bytes()).decode()
        return f"data:{mime};base64,{payload}"

    def _persist(
        self,
        observation: Observation,
        result: ExtractionResult,
        *,
        replacing: Extraction | None,
        usage: Any = None,
    ) -> Extraction:
        """Store the interpretation, overwriting an earlier one only on an explicit re-run."""
        classification = (
            ExtractionClass.DISCARD if not result.belongs_to_event else result.classification
        )
        values = {
            "model": self.model,
            "prompt_version": self.prompt_version,
            "classification": classification,
            "confidence": result.confidence,
            "payload": result.model_dump(mode="json"),
            "geocode_query": result.geocode_query[:300],
            "visual_summary": result.visual_summary,
            "text_image_conflict": result.text_image_conflict,
            "input_tokens": getattr(usage, "input_tokens", 0) or 0,
            "output_tokens": getattr(usage, "output_tokens", 0) or 0,
            "created_at": timezone.now(),
        }
        if replacing:
            for field, value in values.items():
                setattr(replacing, field, value)
            replacing.save()
            return replacing
        return Extraction.objects.create(observation=observation, **values)
