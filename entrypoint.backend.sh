#!/bin/bash
set -e

echo "=== Workflow Backend Starting ==="
echo "Database: configured"
echo "Temporal: ${TEMPORAL_ADDRESS}"
echo "API bind: ${API_HOST}:${API_PORT}"

# Run database migrations (let stderr through for diagnostics)
echo "Running database migrations..."
cd /app
alembic upgrade head || echo "⚠️ Alembic migration failed — check database connection"

# Graceful shutdown: forward signals to background worker
cleanup() {
    echo "Shutting down worker (PID $WORKER_PID)..."
    kill "$WORKER_PID" 2>/dev/null
    wait "$WORKER_PID" 2>/dev/null
    echo "Worker stopped."
}
trap cleanup SIGTERM SIGINT

# Start Temporal worker in background
echo "Starting Temporal worker (background)..."
python -m workflow.temporal.worker &
WORKER_PID=$!

# Start FastAPI server (foreground, replaces shell)
echo "Starting FastAPI server..."
exec uvicorn app.main:app \
    --host "${API_HOST}" \
    --port "${API_PORT}" \
    --log-level info \
    --no-access-log
