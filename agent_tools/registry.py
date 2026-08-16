"""
Which tools each agent gets.

Grouping is not organization, it is enforcement. The frontier agent must be structurally
incapable of reading a post, and that is guaranteed by what is absent from a list rather
than by a sentence in a prompt asking it not to.

Note:
    `run_matching_pass` is deliberately in no toolset. It rewrites every proposal for an
    event, so an agent calling it mid-conversation would invalidate the pairings it had
    just reasoned about. It runs on a schedule; the agent reads its output.
"""

from agent_tools.check_coverage import check_coverage
from agent_tools.create_harvest_job import create_harvest_job
from agent_tools.draft_outreach import draft_outreach
from agent_tools.find_gaps import find_gaps
from agent_tools.get_actor_contacts import get_actor_contacts
from agent_tools.get_balance import get_balance
from agent_tools.get_frontier import get_frontier
from agent_tools.match_resource import match_resource
from agent_tools.propose_match import propose_match
from agent_tools.road_distance import road_distance

# Reads `FrontierNode`, writes `HarvestJob`. Reaches no Observation through either.
FRONTIER_TOOLS = [
    get_frontier,
    create_harvest_job,
]

# Ordered the way an operator works: connect first, then check, then act.
COORDINATION_TOOLS = [
    match_resource,
    check_coverage,
    find_gaps,
    get_balance,
    get_actor_contacts,
    road_distance,
    propose_match,
    draft_outreach,
]

TOOLSETS = {
    "frontier": FRONTIER_TOOLS,
    "coordination": COORDINATION_TOOLS,
}

ALL_TOOLS = FRONTIER_TOOLS + COORDINATION_TOOLS


def get_toolset(name: str) -> list:
    """
    Look up a toolset by name.

    Args:
        name (str): A key of `TOOLSETS`.

    Returns:
        list: The tools, ready to hand to `create_deep_agent`.

    Raises:
        KeyError: On an unknown name, rather than returning an empty list. An agent built
            with no tools fails much later and much less obviously.
    """
    if name not in TOOLSETS:
        raise KeyError(f"unknown toolset {name!r}; expected one of {sorted(TOOLSETS)}")
    return TOOLSETS[name]
