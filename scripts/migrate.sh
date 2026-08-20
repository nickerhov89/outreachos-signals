#!/bin/bash
# Apply schema/*.sql to polza-portal PostgreSQL
# Reads DATABASE_URL from .env
set -euo pipefail
cd "$(dirname "$0")/.."

if [ ! -f .env ]; then
  echo "ERROR: .env not found. cp .env.example .env first." >&2
  exit 1
fi

set -a; source .env; set +a

if [ -z "${DATABASE_URL:-}" ]; then
  echo "ERROR: DATABASE_URL not set in .env" >&2
  exit 1
fi

for f in schema/*.sql; do
  echo ">>> $f"
  psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f "$f"
done
echo "All migrations applied."
