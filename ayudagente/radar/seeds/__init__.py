"""
Registry of loadable datasets.

One entry per dataset rather than one management command per dataset, so adding a scenario
means adding a module here instead of another command that does the same thing under a
different name. Every seed owns the name of the `Event` it hangs off, which is what makes
clearing it a single cascading delete.
"""

from ayudagente.radar.seeds import demo, pilot, taxonomy
from ayudagente.radar.seeds.base import Counts, Seed, Writer

SEEDS: dict[str, Seed] = {seed.name: seed for seed in (taxonomy.SEED, pilot.SEED, demo.SEED)}

__all__ = ["SEEDS", "Counts", "Seed", "Writer"]
