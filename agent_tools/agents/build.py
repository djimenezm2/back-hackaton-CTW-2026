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
"""

from functools import lru_cache
from pathlib import Path

from deepagents import create_deep_agent
from langgraph.graph.state import CompiledStateGraph

from agent_tools.agents.checkpointer import get_checkpointer
from agent_tools.agents.llm import build_chat_model
from agent_tools.registry import get_toolset
from ayudagente.radar.models import Event

PROMPTS_DIR = Path(__file__).parent / "prompts"

# Country names for the prompt. The gazetteer is global; the demo is not.
COUNTRY_NAMES = {"CO": "Colombia"}


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


def render_prompt(name: str, event: Event) -> str:
    """
    Fill a prompt template with the facts of one event.

    Returns:
        str: The system prompt for a conversation about this event.
    """
    return load_prompt(name).format(
        event_id=event.id,
        event_name=event.name,
        hazard=event.get_hazard_display(),
        occurred_at=event.occurred_at.strftime("%d %B %Y, %H:%M UTC"),
        country_name=COUNTRY_NAMES.get(event.country_code, event.country_code),
    )


def build_agent(toolset: str, event: Event, checkpointer=None) -> CompiledStateGraph:
    """
    Build one agent: its toolset, its prompt bound to an event, and the shared model.

    Args:
        toolset (str): A key of `TOOLSETS` — also the name of the prompt template.
        event (Event): The event this conversation is about.
        checkpointer: Override for tests. Defaults to the shared Postgres saver.

    Returns:
        CompiledStateGraph: Ready to `stream`.

    Raises:
        KeyError: On an unknown toolset.
        LLMNotConfigured: When the API key is missing.

    Note:
        Rebuilt per request rather than cached. Compiling is cheap next to a model call,
        and a cached graph would hold a prompt bound to whichever event happened to be
        first — a bug that surfaces only when a second emergency starts.
    """
    return create_deep_agent(
        model=build_chat_model(),
        tools=get_toolset(toolset),
        system_prompt=render_prompt(toolset, event),
        checkpointer=checkpointer if checkpointer is not None else get_checkpointer(),
        name=f"ayudagente-{toolset}",
    )
