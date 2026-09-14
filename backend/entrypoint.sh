#!/bin/sh
# Apply migrations before serving, so a fresh `docker compose up` yields a ready schema.
# Compose already gates on the db healthcheck; this retry loop covers the short window
# where Postgres accepts connections but is still finishing recovery.
set -e

echo "Applying database migrations..."
attempt=1
until alembic upgrade head; do
  if [ "$attempt" -ge 10 ]; then
    echo "Migrations failed after $attempt attempts. Is DATABASE_URL correct and Postgres reachable?" >&2
    exit 1
  fi
  echo "  migration attempt $attempt failed; retrying in 3s..."
  attempt=$((attempt + 1))
  sleep 3
done
echo "Migrations applied."

exec "$@"
