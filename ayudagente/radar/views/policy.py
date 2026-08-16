"""
What the API shows by default.

Two constants, in one place because several endpoints have to agree on them. If the graph
draws an edge the match list refuses to show, the coordinator sees a line on the map with no
row behind it and concludes the dashboard is broken.

Note:
    Both leave out what a decision already closed — covered and expired requirements, failed
    and discarded matches. Surfacing those reopens a question somebody already answered.
"""

from ayudagente.radar.choices import MatchStatus, RequirementStatus

# Live work, the only thing worth drawing on a map
OPEN_REQUIREMENT_STATUSES = (RequirementStatus.OPEN, RequirementStatus.PARTIAL)

# Reported but uncorroborated. Shown when asked for, never matched, never written to
QUARANTINED_STATUSES = (RequirementStatus.UNVERIFIED,)

# Matches nobody has ruled out yet
VISIBLE_MATCH_STATUSES = (
    MatchStatus.PROPOSED,
    MatchStatus.CONTACTED,
    MatchStatus.CONFIRMED,
    MatchStatus.DELIVERED,
)
