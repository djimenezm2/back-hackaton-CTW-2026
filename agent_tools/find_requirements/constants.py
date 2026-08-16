"""Tuning knobs and the enum values the model is shown, derived so they cannot drift."""

from ayudagente.radar.choices import Direction, LocationPrecision

# The agent reads to decide, not to browse. Ten rows is a decision; fifty is a context bill.
DEFAULT_LIMIT = 10
MAX_LIMIT = 25
# Enough of the original wording to judge a case, not enough to quote a whole post
NOTE_CHARS = 160
# A miss should show the whole taxonomy; the cap is a backstop, not an expectation
MAX_CATALOG_ROWS = 40

DIRECTION_VALUES = ", ".join(Direction.values)
PRECISION_VALUES = ", ".join(LocationPrecision.values)
