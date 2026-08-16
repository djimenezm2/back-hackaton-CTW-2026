#!/usr/bin/env bash
#
# Redeploy the API from the tip of origin/main.
#
# Usage:
#   deploy.sh              Pull, rebuild, recreate, migrate, collect static
#   deploy.sh --seed       The above, then load the taxonomy, gazetteer and seed fixtures
#   deploy.sh --reset      Drop the database volume first, then deploy and seed from scratch
#
# Note:
#   The body sits in main() so bash parses the whole script before `git reset` rewrites it.
#   Harvesting is never started here: the workers profile stays down until brought up by hand.
set -euo pipefail

ROOT=${ROOT:-/opt/ayudagente}
APP=$ROOT/app
ENV_FILE=$ROOT/.env
BRANCH=${BRANCH:-main}

compose() {
    docker compose --env-file "$ENV_FILE" -f "$APP/docker-compose.prod.yml" "$@"
}

main() {
    local seed=0 reset=0
    for arg in "$@"; do
        case $arg in
            --seed) seed=1 ;;
            --reset) reset=1; seed=1 ;;
            *) echo "unknown flag: $arg" >&2; exit 2 ;;
        esac
    done

    test -f "$ENV_FILE" || { echo "missing $ENV_FILE" >&2; exit 1; }

    echo "==> fetching origin/$BRANCH"
    git -C "$APP" fetch --prune origin
    git -C "$APP" reset --hard "origin/$BRANCH"
    echo "    now at $(git -C "$APP" rev-parse --short HEAD) $(git -C "$APP" log -1 --format=%s)"

    if [ "$reset" = 1 ]; then
        echo "==> dropping the database volume"
        compose down -v
    fi

    echo "==> building"
    compose build

    echo "==> starting the data services"
    compose up -d db redis

    echo "==> migrating"
    compose run --rm web python manage.py migrate --noinput

    if [ "$seed" = 1 ]; then
        echo "==> loading reference data and fixtures"
        compose run --rm web python manage.py load_taxonomy
        compose run --rm web python manage.py load_gazetteer CO
        compose run --rm web python manage.py seed
    fi

    echo "==> collecting static files"
    compose run --rm web python manage.py collectstatic --noinput

    echo "==> starting the API"
    compose up -d web
    compose ps
}

main "$@"
