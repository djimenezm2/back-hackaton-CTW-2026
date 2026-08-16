"""
Search open needs and offers.

Split by role: `constants` for the knobs, `input` for the schema the model reads, `output`
for row and error shapes, `find_requirements` for the guards and the single service call.
"""

from agent_tools.find_requirements.find_requirements import find_requirements

__all__ = ["find_requirements"]
