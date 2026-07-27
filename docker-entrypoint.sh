#!/bin/sh
set -eu

case "${1:-}" in
  app.main:app|app.operator_main:app|app.jobs_main:app) module="$1" ;;
  *) echo "unsupported service module" >&2; exit 64 ;;
esac

exec /app/.venv/bin/uvicorn "$module" --host 0.0.0.0 --port "${PORT:-8080}" --no-access-log
