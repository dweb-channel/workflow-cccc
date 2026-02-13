# Backend - FastAPI Workflow Engine

## Quick Start

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -e .
make dev          # Starts Temporal + Worker + FastAPI
```

## Available Commands

```
make dev      - Start all services (Temporal + Worker + FastAPI)
make stop     - Stop all services
make temporal - Start Temporal Server only
make worker   - Start Worker only
make api      - Start FastAPI only
make logs     - View background service logs
make clean    - Clean log files
```

## API Endpoints (v2)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/v2/workflows` | List workflows |
| GET | `/api/v2/workflows/{id}` | Get workflow detail |
| POST | `/api/v2/workflows` | Create workflow |
| PUT | `/api/v2/workflows/{id}` | Update workflow |
| POST | `/api/v2/workflows/{id}/run` | Execute workflow |
| GET | `/api/v2/workflows/{id}/runs` | List run history |
| GET | `/api/v2/sse/stream/{run_id}` | SSE event stream |

## Run Tests

```bash
source .venv/bin/activate
pytest tests/ -v
```
