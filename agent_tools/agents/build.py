"""
Assembling an agent from a toolset, a prompt and a model.

One builder for both agents, because they differ only in which tools they hold and what
their prompt says. Everything else — the model, the checkpointer, how the event is
described — is identical, and duplicating it is how two agents quietly start behaving
differently.

Note:
    The prompt is rendered with the event's own facts rather than told to call a tool for
    them. Which disaster this is, where and when, is context the agent needs in every turn
    and never has to decide about, so it costs one string interpolation instead of a round
    trip and a slot in the toolset.

    Where the coordinator is arrives the same way and for the same reason. It is the one
    fact no tool can look up — the browser is the only thing that knows it — and half the
    questions asked during an emergency are implicitly about it.
"""

from functools import lru_cache
from pathlib import Path
from typing import NamedTuple

from deepagents import create_deep_agent
from langgraph.graph.state import CompiledStateGraph

from agent_tools.agents.checkpointer import get_checkpointer
from agent_tools.agents.llm import build_chat_model
from agent_tools.registry import get_toolset
from ayudagente.radar.models import Event

PROMPTS_DIR = Path(__file__).parent / "prompts"

# Country names for the prompt. The gazetteer is global; the demo is not.
COUNTRY_NAMES = {"CO": "Colombia"}

# Five decimals is about a metre — finer than any browser fix, and short enough to read
COORDINATE_DECIMALS = 5


class Coordinates(NamedTuple):
    """
    Where the person asking is.

    Note:
        Named rather than a bare pair because a tuple of two floats reverses without
        complaining, and a swapped lat/lon is a valid point somewhere else on Earth.
    """

    lat: float
    lon: float


def describe_location(location: Coordinates | None) -> str:
    """
    Say where the coordinator is, in terms the prompt can use.

    Returns:
        str: One sentence. An absent position is stated rather than left out, because a
            prompt that simply omits it reads as "location does not apply here" and the
            agent stops asking for one.
    """
    if location is None:
        return (
            "The coordinator has not shared their position. Ask where they are whenever "
            "an answer depends on it."
        )
    return (
        f"The coordinator is at latitude {location.lat:.{COORDINATE_DECIMALS}f}, "
        f"longitude {location.lon:.{COORDINATE_DECIMALS}f}. Pass those as `lat` and `lon` "
        'when they say "aquí" or "cerca de mí" and name no place.'
    )


@lru_cache(maxsize=8)
def load_prompt(name: str) -> str:
    """
    Read a prompt template from disk, once per process.

    Args:
        name (str): File stem under `prompts/`.

    Returns:
        str: The raw template, with `{placeholders}` still in it.

    Raises:
        FileNotFoundError: Rather than falling back to an empty prompt, which would produce
            an agent that runs and behaves arbitrarily — the worst possible failure here.
    """
    path = PROMPTS_DIR / f"{name}.md"
    if not path.exists():
        raise FileNotFoundError(f"missing prompt template: {path}")
    return path.read_text(encoding="utf-8")


def render_prompt(name: str, event: Event, location: Coordinates | None = None) -> str:
    """
    Fill a prompt template with the facts of one event.

    Args:
        name (str): File stem under `prompts/`.
        event (Event): The event this conversation is about.
        location (Coordinates | None): Where the coordinator is, when the browser shared
            it. A template that has no use for it simply does not name the placeholder.

    Returns:
        str: The system prompt for a conversation about this event.
    """
    return load_prompt(name).format(
        event_id=event.id,
        event_name=event.name,
        hazard=event.get_hazard_display(),
        occurred_at=event.occurred_at.strftime("%d %B %Y, %H:%M UTC"),
        country_name=COUNTRY_NAMES.get(event.country_code, event.country_code),
        user_location=describe_location(location),
    )


def build_agent(
    toolset: str, event: Event, location: Coordinates | None = None, checkpointer=None
) -> CompiledStateGraph:
    """
    Build one agent: its toolset, its prompt bound to an event, and the shared model.

    Args:
        toolset (str): A key of `TOOLSETS` — also the name of the prompt template.
        event (Event): The event this conversation is about.
        location (Coordinates | None): Where the coordinator is, for this turn.
        checkpointer: Override for tests. Defaults to the shared Postgres saver.

    Returns:
        CompiledStateGraph: Ready to `stream`.

    Raises:
        KeyError: On an unknown toolset.
        LLMNotConfigured: When the API key is missing.

    Note:
        Rebuilt per request rather than cached. Compiling is cheap next to a model call,
        and a cached graph would hold a prompt bound to whichever event happened to be
        first — a bug that surfaces only when a second emergency starts. Rebuilding is
        also what lets the position follow a coordinator who moves between turns: the
        prompt is re-rendered every time, while the thread keeps its history.
    """
    return create_deep_agent(
        model=build_chat_model(),
        tools=get_toolset(toolset),
        system_prompt=render_prompt(toolset, event, location),
        checkpointer=checkpointer if checkpointer is not None else get_checkpointer(),
        name=f"ayudagente-{toolset}",
    )
