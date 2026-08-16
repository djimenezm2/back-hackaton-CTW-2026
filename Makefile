COMPOSE ?= docker compose
SERVICE ?= db

UV ?= uv
MANAGE = $(UV) run manage.py

# Extra flags for pytest or manage.py, to narrow a run while working.
ARGS ?=

ENV_FILE ?= .env
ENV_TEMPLATE ?= .env.example

# `init` is what creates the env file, so it runs before the guard below applies.
BOOTSTRAP_GOALS = init help

# Django reads the database credentials from it, so no other target works without it.
$(if $(filter-out $(BOOTSTRAP_GOALS),$(or $(MAKECMDGOALS),help)),\
	$(if $(wildcard $(ENV_FILE)),,$(error $(ENV_FILE) not found: run make init)))

# Set LIVE to anything to include tests that reach Postgres, Azure or Apify.
LIVE ?=

# `-m ""` clears the `-m "not live"` in `pyproject.toml`, so the whole suite runs.
MARKERS = $(if $(LIVE),-m "",)

.DEFAULT_GOAL := help
.PHONY: help init up down restart ps logs build rebuild \
        check lint format comments types test migrate migrations shell run superuser apikey \
        seed unseed eval harvest pipeline worker

help: ## Show available commands
	@awk 'BEGIN {FS = ":.*##"; printf "Available commands:\n"} /^[a-zA-Z0-9_.-]+:.*##/ {printf "  make %-22s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

init: ## Create .venv, install deps and seed .env from .env.example
	@test -f $(ENV_FILE) || { cp $(ENV_TEMPLATE) $(ENV_FILE) && echo "created $(ENV_FILE): fill in the secrets"; }
	$(UV) sync

up: ## Build and start Postgres and Redis
	$(COMPOSE) up --build -d

down: ## Stop the local stack
	$(COMPOSE) down

restart: ## Restart a service (make restart SERVICE=redis)
	$(COMPOSE) restart $(SERVICE)

ps: ## Show container status
	$(COMPOSE) ps

logs: ## Follow logs (make logs SERVICE=redis)
	$(COMPOSE) logs -f $(SERVICE)

build: ## Build stack images
	$(COMPOSE) build

rebuild: ## Rebuild and recreate the stack
	$(COMPOSE) up --build -d --force-recreate

check: lint format comments types test ## Lint, format, comments, types and the hermetic suite

lint: ## Ruff lint
	$(UV) run ruff check .

format: ## Ruff format check
	$(UV) run ruff format --check .

comments: ## Flag multi-line comment blocks; rationale belongs in a docstring
	$(UV) run tools/check_comments.py ayudagente agent_tools backend tools

types: ## Pyrefly type check
	$(UV) run pyrefly check

test: ## Run the suite (make test LIVE=1 to include tests that need real services)
	$(UV) run pytest $(MARKERS) $(ARGS)

seed: ## Load the seed datasets (idempotent). make seed ARGS="--list" to see them
	$(MANAGE) seed $(ARGS)

unseed: ## Delete the seed datasets
	$(MANAGE) seed --clear $(ARGS)

harvest: ## Run the harvest jobs the frontier queued (ARGS="--limit 3 --pipeline")
	$(MANAGE) harvest $(ARGS)

pipeline: ## Read an event's posts into requirements (ARGS="--limit 20")
	$(MANAGE) run_pipeline $(ARGS)

worker: ## Run a Celery worker
	$(UV) run celery -A backend worker -l info

eval: ## Score the extraction prompt against real posts (calls the model)
	$(MANAGE) eval_extraction $(ARGS)

migrations: ## Generate migrations
	$(MANAGE) makemigrations $(ARGS)

migrate: ## Apply migrations
	$(MANAGE) migrate $(ARGS)

shell: ## Django shell
	$(MANAGE) shell

run: ## Development server
	$(MANAGE) runserver $(ARGS)

superuser: ## Create an admin user
	$(MANAGE) createsuperuser

apikey: ## Mint an API key into .env. ARGS="--replace" drops the existing ones
	$(MANAGE) apikey $(ARGS)
