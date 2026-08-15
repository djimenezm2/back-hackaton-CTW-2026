# back-hackaton-CTW-2026

Basic Django + PostgreSQL project skeleton.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # adjust DB_* if needed

docker compose up -d          # Postgres 16

python manage.py migrate
python manage.py runserver
```

Admin at `http://127.0.0.1:8000/admin/`.

Add apps with `python manage.py startapp <name>`, then register in `INSTALLED_APPS`.
