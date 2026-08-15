# back-hackaton-CTW-2026

Basic Django + PostgreSQL project skeleton. Dependencies managed with [uv](https://docs.astral.sh/uv/).

## Setup

```bash
uv sync                       # creates .venv and installs deps
cp .env.example .env          # adjust DB_* if needed

docker compose up -d          # Postgres 16

uv run manage.py migrate
uv run manage.py runserver
```

Admin at `http://127.0.0.1:8000/admin/`.

Add dependencies with `uv add <package>`. Add apps with `uv run manage.py startapp <name>`, then register in `INSTALLED_APPS`.
