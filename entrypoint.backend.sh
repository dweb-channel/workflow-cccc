#!/bin/sh
set -e

# ---- Work-Flow Backend Entrypoint ----
# Runs DB migration, starts Temporal Worker (background), then FastAPI (foreground).
# Handles SIGTERM for graceful shutdown.

WORKER_PID=""
API_PID=""

cleanup() {
    echo "[entrypoint] Shutting down..."
    # Stop FastAPI first (stop accepting requests)
    if [ -n "$API_PID" ] && kill -0 "$API_PID" 2>/dev/null; then
        kill -TERM "$API_PID"
        wait "$API_PID" 2>/dev/null || true
    fi
    # Then stop Worker (let in-flight activities finish)
    if [ -n "$WORKER_PID" ] && kill -0 "$WORKER_PID" 2>/dev/null; then
        kill -TERM "$WORKER_PID"
        wait "$WORKER_PID" 2>/dev/null || true
    fi
    exit 0
}

trap cleanup TERM INT

# 1) Database migration
echo "[entrypoint] Running database migrations..."
python -m alembic upgrade head
echo "[entrypoint] Migrations complete."

# 2) Start Temporal Worker in background
echo "[entrypoint] Starting Temporal Worker..."
python -m workflow.temporal.worker &
WORKER_PID=$!
echo "[entrypoint] Worker started (PID=$WORKER_PID)"

# 3) Start FastAPI in background (shell stays PID 1 for signal handling)
echo "[entrypoint] Starting FastAPI on ${API_HOST:-0.0.0.0}:${API_PORT:-8000}..."
uvicorn app.main:app \
    --host "${API_HOST:-0.0.0.0}" \
    --port "${API_PORT:-8000}" \
    --no-access-log &
API_PID=$!
echo "[entrypoint] FastAPI started (PID=$API_PID)"

# Wait for the API server (primary process).
# On SIGTERM: trap fires → cleanup kills both → exit 0.
# On API crash: wait returns → cleanup kills worker → exit.
wait "$API_PID" 2>/dev/null || true
echo "[entrypoint] FastAPI exited, shutting down..."
cleanup
