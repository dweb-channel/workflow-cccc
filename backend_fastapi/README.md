# FastAPI Backend (Workflow Ops)

## Run
```bash
cd backend_fastapi
python -m venv .venv
source .venv/bin/activate
pip install -e .
export PYTHONPATH=../src
export TEMPORAL_ADDRESS=localhost:7233
export TEMPORAL_TASK_QUEUE=business-workflow-task-queue
uvicorn app.main:app --reload --port 4000
```

## Endpoints
- GET /api/workflows
- GET /api/workflows/{id}
- GET /api/workflows/{id}/runs
- GET /api/workflows/{id}/logs
- POST /api/workflows/{id}/run
- POST /api/workflows/{id}/save

## Notes
- Current implementation uses in-memory data.
- /run 会通过 Temporal client 触发 `BusinessWorkflow`。
- 若 Temporal 未启动，/run 会返回 503。
