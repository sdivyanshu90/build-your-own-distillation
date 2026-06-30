#!/usr/bin/env bash
# Container entrypoint — dispatches on the first argument.
#   api      → run the HTTP API (Uvicorn, multi-worker)
#   worker   → run a Celery worker
#   beat     → run the Celery beat scheduler (optional periodic tasks)
#   migrate  → apply Alembic migrations then exit
#   bash/sh  → drop to a shell (debugging)
set -euo pipefail

COMMAND="${1:-api}"
shift || true

API_HOST="${DISTILLERY_API__HOST:-0.0.0.0}"
API_PORT="${DISTILLERY_API__PORT:-8000}"
WEB_CONCURRENCY="${WEB_CONCURRENCY:-2}"
WORKER_CONCURRENCY="${DISTILLERY_QUEUE__WORKER_CONCURRENCY:-2}"
CELERY_APP="distillery.infrastructure.queue.celery_app:celery_app"

case "${COMMAND}" in
  api)
    exec uvicorn distillery.api.app:create_app --factory \
      --host "${API_HOST}" --port "${API_PORT}" \
      --workers "${WEB_CONCURRENCY}" --no-server-header --proxy-headers
    ;;
  worker)
    exec celery -A "${CELERY_APP}" worker \
      --loglevel="${DISTILLERY_LOG_LEVEL:-INFO}" \
      --concurrency="${WORKER_CONCURRENCY}"
    ;;
  beat)
    exec celery -A "${CELERY_APP}" beat --loglevel="${DISTILLERY_LOG_LEVEL:-INFO}"
    ;;
  migrate)
    exec alembic upgrade head
    ;;
  bash | sh)
    exec "${COMMAND}" "$@"
    ;;
  *)
    echo "Unknown command: ${COMMAND}" >&2
    echo "Usage: entrypoint.sh [api|worker|beat|migrate|bash]" >&2
    exit 64
    ;;
esac
