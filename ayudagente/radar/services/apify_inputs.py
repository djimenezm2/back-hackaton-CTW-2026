"""
What each Apify Actor expects, which is not what any of the others expect.

Every Actor has its own input schema and there is no shared shape. The first live run made
that expensive to learn: the code sent `{"searchQuery": ...}` to all four, three ignored it
silently, and the X scraper returned ten rows of `{"noResults": true}` — a successful run,
billed, carrying nothing. Nothing failed. The job was marked `done`.

So the translation lives here, one function per platform, checked against each Actor's real
schema. Everything above this module speaks in toponyms and axis terms and never in fields.

Note:
    The Actors are the ones the pilot proved, not the plausible ones. `apify/facebook-posts-
    scraper` cannot search at all — `startUrls` is required and it reads pages — so it can
    never serve a sweep no matter what it is sent.

    The item limit is **per search term** on three of the four, so a batch of eight toponyms
    with a limit of two hundred asks for sixteen hundred items and bills for them. The limit
    is divided here, which is the difference between a ten-cent sweep and a sixteen-dollar
    one.

    Only X batches with OR. Instagram and TikTok take arrays and run each entry separately;
    Facebook takes a single fuzzy string. Batching is therefore per-platform and not a
    property of the query, which is why `build_sweep_query` returning one string was wrong.
"""

from dataclasses import dataclass, field
from datetime import UTC, date

from ayudagente.radar.choices import Platform

# The Actors the pilot proved, with what each one charges per item where it is known
APIFY_ACTOR_BY_PLATFORM = {
    Platform.X: "kaitoeasyapi/twitter-x-data-tweet-scraper-pay-per-result-cheapest",
    Platform.INSTAGRAM: "apify/instagram-hashtag-scraper",
    Platform.FACEBOOK: "scraper_one/facebook-posts-search",
    Platform.TIKTOK: "clockworks/tiktok-scraper",
}

# The X Actor refuses anything smaller and treats the number as a floor, not a cap
MIN_ITEMS_PER_TERM = 20

# Instagram rejects a term carrying any of these, and rejects the whole run with it
PUNCTUATION = set("!?.,:;-+=*&%$#@/~^|<>()[]{}\"'`\\")

MAX_TOPONYMS = {
    Platform.X: 8,
    Platform.INSTAGRAM: 4,
    Platform.FACEBOOK: 3,
    Platform.TIKTOK: 4,
}


@dataclass(frozen=True)
class Query:
    """
    A search expressed in the domain's terms, before any Actor sees it.

    Attributes:
        toponyms (list[str]): Place names. Never empty — invariant 9.
        qualified (list[str]): The same places carrying their region, for platforms that
            tokenize a query instead of honouring quoted phrases. Falls back to `toponyms`.
        axis_terms (list[str]): Demand or supply vocabulary, in the event's language.
        hashtags (list[str]): Event hashtags, already carrying their `#`.
        negatives (list[str]): Other emergencies' terms, excluded where the platform can.
        limit (int): Items wanted from the whole job, not from each term.
        language (str): ISO 639-1, where the Actor accepts one.
        since (date | None): Oldest post worth having.
    """

    toponyms: list[str]
    qualified: list[str] = field(default_factory=list)
    axis_terms: list[str] = field(default_factory=list)
    hashtags: list[str] = field(default_factory=list)
    negatives: list[str] = field(default_factory=list)
    limit: int = 100
    language: str = ""
    since: date | None = None

    def places(self) -> list[str]:
        """
        The place names to search with, qualified where the platform needs it.

        Note:
            A platform that tokenizes turns "Río Quito" into two words and matches Quito,
            Ecuador — thirty posts in one live sweep. Carrying the region forces both words
            to appear and the leak closes.
        """
        return self.qualified or self.toponyms


def build_input(platform: str, query: Query) -> dict:
    """
    Translate a search into the payload one Actor accepts.

    Args:
        platform (str): A `Platform` value.
        query (Query): What to look for.

    Returns:
        dict: The Actor's `run_input`, ready to send.

    Raises:
        ValueError: On an unknown platform, or on a query with no toponym. The second is
            invariant 9: a query without one pulls in every other country's disaster, and the
            first live run showed how quietly a bad payload fails.
    """
    if not query.toponyms:
        raise ValueError("a query without a toponym would pull in other countries' disasters")

    builders = {
        Platform.X: _for_x,
        Platform.INSTAGRAM: _for_instagram,
        Platform.FACEBOOK: _for_facebook,
        Platform.TIKTOK: _for_tiktok,
    }
    builder = builders.get(Platform(platform))
    if builder is None:
        raise ValueError(f"no Apify Actor configured for platform {platform!r}")
    return builder(query)


def _for_x(query: Query) -> dict:
    """
    X, the only platform whose search syntax batches with OR.

    Note:
        One search term carrying every toponym, because `maxItems` applies per term. Eight
        terms would multiply the bill by eight for the same coverage.

        Place group AND axis group, not one flat OR. A live run showed why: "Lloró" is a
        municipality of Chocó and also the Spanish for "he cried", so a flat OR returned
        "lloro un poquito". Requiring an axis word alongside the place costs nothing and
        removes a whole class of homonym.
    """
    places = _group(_capped(query.toponyms, Platform.X))
    axis = _group(query.axis_terms + query.hashtags)
    excluded = " ".join(f'-"{term}"' for term in query.negatives)

    payload = {
        "searchTerms": [" ".join(part for part in (places, axis, excluded) if part)],
        "maxItems": max(query.limit, MIN_ITEMS_PER_TERM),
        "queryType": "Latest",
    }
    if query.language:
        payload["lang"] = query.language
    if query.since:
        payload["since_time"] = str(int(_midnight(query.since)))
    return payload


def _for_instagram(query: Query) -> dict:
    """
    Instagram, which searches hashtags or keywords and never free text.

    Note:
        `keywordSearch` is on because toponyms are multi-word — "Valle del Cauca" as a
        hashtag becomes `#valledelcauca`, which is a different and much smaller thing.

        Punctuation is stripped because the Actor validates every term against a character
        pattern and rejects the *whole run* when one fails. "Bogotá D.C." cost a live sweep
        of the entire support zone that way.
    """
    terms = [_searchable(term) for term in _capped(query.places(), Platform.INSTAGRAM)]
    terms = [term for term in terms if term]
    if not terms:
        raise ValueError("no toponym survived Instagram's character rules")

    return {
        "hashtags": terms,
        "keywordSearch": True,
        "resultsType": "posts",
        "resultsLimit": _per_term(query.limit, len(terms)),
    }


def _for_facebook(query: Query) -> dict:
    """
    Facebook, whose search takes one fuzzy string and cannot be batched with operators.

    Note:
        Toponyms and one axis term joined by spaces, which is what the pilot's three working
        Facebook queries looked like. Words are deduplicated because every qualified toponym
        repeats its region, and "Chocó" three times in a fuzzy search only dilutes it.

        Negatives are dropped: the Actor has no exclusion syntax, so passing them would put
        the excluded words *into* the search.
    """
    terms = _capped(query.places(), Platform.FACEBOOK) + query.axis_terms[:1]
    words = dict.fromkeys(word for term in terms for word in term.split())
    payload = {
        "query": " ".join(words),
        "resultsCount": min(max(query.limit, 1), 200),
        "searchType": "latest",
    }
    if query.since:
        payload["startDate"] = query.since.isoformat()
    return payload


def _for_tiktok(query: Query) -> dict:
    """
    TikTok, which runs each entry of `searchQueries` as its own search.

    Note:
        One entry per toponym with an axis term appended, rather than an OR expression —
        TikTok has no boolean syntax, so an OR string would be searched literally.
    """
    terms = _capped(query.places(), Platform.TIKTOK)
    axis = query.axis_terms[0] if query.axis_terms else ""
    return {
        "searchQueries": [f"{term} {axis}".strip() for term in terms],
        "resultsPerPage": _per_term(query.limit, len(terms)),
        "searchSection": "/video",
    }


def _searchable(term: str) -> str:
    """A toponym with the characters Instagram refuses removed."""
    return " ".join("".join(c for c in term if c not in PUNCTUATION).split())


def _group(terms: list[str]) -> str:
    """One OR group, parenthesised so it ANDs against the next."""
    if not terms:
        return ""
    joined = " OR ".join(f'"{term}"' for term in terms)
    return f"({joined})" if len(terms) > 1 else joined


def _capped(toponyms: list[str], platform: str) -> list[str]:
    """As many toponyms as this platform's query can usefully carry."""
    return toponyms[: MAX_TOPONYMS[Platform(platform)]]


def _per_term(limit: int, terms: int) -> int:
    """
    Divide a job's item budget across its search terms.

    Note:
        The Actors treat their limit as per-term, so the whole job costs limit times terms
        unless it is divided here. At least one, or the Actor is asked for nothing.
    """
    return max(1, limit // max(terms, 1))


def _midnight(day: date) -> float:
    """A date as a unix timestamp, which is what the X Actor's time filters take."""
    from datetime import datetime

    return datetime(day.year, day.month, day.day, tzinfo=UTC).timestamp()
