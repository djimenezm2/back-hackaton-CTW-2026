# AyudAgente — backend

An autonomous agent that discovers, scopes and prioritizes actionable information during a
disaster, then connects the people who need help with the people offering it. Django 5 +
PostgreSQL 16 with PostGIS and pgvector.

Read [`HANDBOOK.md`](HANDBOOK.md) for the search strategy and [`docs/data-model.md`](docs/data-model.md)
for how the models relate. This file is the short version plus the rules that must not drift.

## Commands

```bash
make init      # .venv, deps, .env from .env.example
make up        # Postgres (PostGIS + pgvector) and Redis
make migrate
make run
make check     # ruff lint + ruff format --check + pyrefly + pytest
```

`make help` lists everything. The database container publishes **5433**, not 5432, so it does
not collide with a Postgres installed on the host.

## Layout

```
backend/          Django project config
ayudagente/       product package — every app lives in here, never at the repo root
    radar/        harvest, graph and search frontier (app label: radar)
        choices.py    all TextChoices, centralized
        models/       split by layer, re-exported from the package
        tests/        next to the code they cover
docs/             architecture documentation
docker/           database image and init scripts
```

New apps go inside `ayudagente/` and register as `ayudagente.<name>` in `INSTALLED_APPS`.

## The architecture decision that governs everything

**The code owns the route. The LLM owns the judgment inside each step.**

Every observation walks the same fixed sequence: classify → extract → read image → build the
geocoding string → geocode → resolve actor → match. Five of those steps call a model; the
*order* is plain Python. Steps 1–4 are deliberately **one** multimodal call with a JSON schema,
because Azure's per-deployment TPM quota is the real bottleneck and because the model resolves
text-vs-image contradictions better when it sees both at once.

An LLM agent runs in exactly two places:

1. **The frontier agent** decides what to harvest next — which municipality, which platform,
   which query, how much to spend. It reads only `FrontierNode` (~50 rows, ~2K tokens) and
   writes `HarvestJob` rows. **It never sees a post.**
2. **Actor adjudication** decides whether two mentions are the same real-world entity, and only
   for pairs the cheap signals could not settle.

Do not turn pipeline steps into agents or subagents. They are high-volume and fixed, not
open-ended, so a reasoning loop buys nothing and costs latency, money and determinism. The
payoff of the fixed route is concrete: a 429 from Azure retries one task instead of corrupting
an agent's message history, 50 observations process in parallel under a concurrency cap, and a
bad field is diagnosed by looking at one step's output rather than re-reading a trace.

## Invariants

Breaking any of these is a bug even when tests pass.

1. `Observation` is never updated or deleted. New information is a new row.
2. `Extraction` never writes into `Observation`.
3. A `Match` past `proposed` is never rewritten by the matching pass — a human is already
   involved.
4. `ContactPoint.allows_automatic_outreach()` fails closed: email to organizations at high
   confidence, nothing else. Anything not explicitly permitted returns False.
5. `Outreach` is only ever created through its idempotency key.
6. Actor merges set `merged_into`; they never delete.
7. Every `Location` carries its precision, and matching enforces a minimum.
8. Every scraping query carries a Colombian toponym, or it pulls in other countries'
   earthquakes.

## Identity resolution is a cascade

Deterministic keys → blocking by municipality → trigram similarity (`pg_trgm`) → embeddings
(`pgvector`) → LLM adjudication. **Embeddings are the fourth signal, not the first**:
"Coliseo Mayor" and "Coliseo Menor" are nearly identical as vectors and are different places.

## Matching runs on an in-memory graph

Postgres is the source of truth; the matching pass loads open requirements into NetworkX,
solves an allocation problem, writes results back and discards the graph. Pairwise greedy
matching leaves needs uncovered that had a solution. Connected-component analysis on that graph
gives the most valuable alert in the system: needs with no reachable supply.

No graph database. The most complex query is a two-hop join with a spatial index.

## Code style

**Everything in files is English** — identifiers, docstrings, comments, docs, commit messages,
log lines, API keys, database identifiers. The exception is content an end user reads: outreach
message bodies and UI strings are Spanish, because the recipients are Colombian. LLM prompts are
written in English; their *output* follows the audience.

Formatting and linting are enforced by `make check`:

- ruff format defaults — double quotes, 100 columns
- ruff lint `E, F, I, UP, B, SIM, RUF`; no `D`, because the repo documents in sectioned prose
- `*/migrations/*` is excluded — Django writes those
- `RUF012` is off inside `models/` — Django's `Meta` is a declarative API, not mutable state
- pyrefly with `django-stubs`, `min-severity = "warn"`, pinned to Python 3.12 to match
  `requires-python`

### Comments

One line, short, saying *what* is done. End-of-line or a single line above. Never multi-line
blocks explaining rationale or alternatives — they bury the logic. If the code already says it,
drop the comment. When rationale matters, compress it into the docstring's `Note:` section.

```python
self.is_organization = self.kind in ORGANIZATION_KINDS
root.setLevel("WARNING")  # quiet by default, no list of names to maintain
```

### Docstrings

Sections, never a wall of prose. A short summary first, then whichever of these apply:
`Args:` / `Returns:` / `Raises:` / `Note:` / `See:`. Args entries carry the type in parens.

Model docstrings say what the model is *for* and why its boundaries fall where they do — the
design decision, not a restatement of the fields. The fields are already in the code.

```python
def allows_automatic_outreach(self) -> bool:
    """
    Decide whether the system may write through this channel without human approval.

    Returns:
        bool: True only when every condition holds. This fails closed, because the
            default when writing to someone during an emergency has to be not to write.
    """
```

### Tests

Next to the code they cover. The default run is hermetic; anything reaching Postgres, Azure or
Apify is marked `live` and excluded, so `make test LIVE=1` is the opt-in.

## Status

**Built:** data model (15 models, migrated), tooling, docker stack.

**Not built yet:** admin registrations, Celery wiring, the harvest/extraction/geocoding/matching
tasks, the frontier agent, the API. Each is its own slice.

**Known gap to respect when building extraction:** `Requirement.evidence` is many-to-many to
`Observation` because one post can legitimately produce several requirements. A post listing
three collection centers produces three. Code that assumes one-post-one-requirement will
silently drop two of them.
