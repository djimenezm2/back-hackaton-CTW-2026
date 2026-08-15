# back-hackaton-CTW-2026

Backend for **AyudAgente** — an autonomous agent that discovers, scopes and prioritizes
actionable information during a disaster, then connects the people who need help with the
people offering it.

Django 5 + PostgreSQL 16 with PostGIS and pgvector. Dependencies managed with
[uv](https://docs.astral.sh/uv/).

## Setup

```bash
make init      # creates .venv, installs deps, seeds .env from .env.example
make up        # builds Postgres+PostGIS+pgvector, starts it and Redis
make migrate
make run
```

`make help` lists every target. Admin at `http://127.0.0.1:8000/admin/`.

## Development

```bash
make check     # ruff lint + ruff format --check + pyrefly + pytest
```

Run those individually with `make lint`, `make format`, `make types`, `make test`.

Formatting is ruff's default, so double quotes. Ruff skips `*/migrations/*` because Django
writes those and reformatting them makes every migration diff unreadable, and `RUF012` is
disabled inside `models/` because Django's `Meta` is a declarative API rather than the
mutable shared state that rule is about.

Type checking uses pyrefly with `django-stubs`, at `min-severity = "warn"` so deprecations
surface instead of rotting under the default error floor. It is pinned to Python 3.12 to
match `requires-python`, not the local interpreter, so anything newer gets flagged here
rather than in someone else's environment.

Tests live next to the code they cover. The default run is hermetic — anything needing
Postgres, Azure or Apify is marked `live` and excluded, so `make test LIVE=1` is the opt-in.

### Ports

The database container publishes **5433**, not 5432, so it does not collide with a Postgres
installed on the host. Redis is on 6379.

### Database extensions

The `postgres:16` image does not ship what the model needs, so `docker/postgres.Dockerfile`
builds on `postgis/postgis:16-3.4` and adds pgvector. On first boot,
`docker/init-extensions.sql` enables:

| Extension | Used for |
|---|---|
| `postgis` | Proximity queries and spatial indexes |
| `vector` | Actor identity resolution by embedding |
| `pg_trgm` | Name similarity — better than embeddings for proper nouns |
| `unaccent` | Normalizing place and actor names |

If you wipe the volume (`docker compose down -v`), these are re-created automatically.

## Layout

```
backend/          Django project config
ayudagente/       product package — all apps live in here
    radar/        harvest, graph and search-frontier app (label: radar)
docs/             architecture and data-model documentation
docker/           database image and init scripts
```

Add apps inside `ayudagente/` rather than at the repository root, and register them as
`ayudagente.<name>` in `INSTALLED_APPS`.

## Documentation

- [`docs/data-model.md`](docs/data-model.md) — what each model is for and how they relate
- [`HANDBOOK.md`](HANDBOOK.md) — the search strategy: how the agent decides what to scrape,
  with per-platform yields and costs measured against a real event

## Dependency notes

`django.contrib.gis` needs GDAL, GEOS and PROJ present on the host. On Fedora:

```bash
sudo dnf install gdal geos proj
```

Add dependencies with `uv add <package>`.
