# LangGraph + Temporal MVP Workflow

This repo contains a minimal, runnable MVP that combines:
- **LangGraph** for agent/role planning and review flow.
- **Temporal** for durable orchestration, human confirmation, and long-running workflow state.

## What it does
- Parses an incoming request.
- Waits for initial user confirmation.
- Runs a LangGraph planning/review pipeline.
- Waits for final user confirmation.
- Returns a structured result.

## Project layout
- `src/workflow/graph.py`: LangGraph planning graph (peer1 plan → peer2 review → foreman summary → dispatch).
- `src/workflow/activities.py`: Temporal activities (parse requirements, run planning graph).
- `src/workflow/workflows.py`: Temporal workflow + signals/queries.
- `src/workflow/run_worker.py`: Worker process.
- `src/workflow/run_demo.py`: Demo runner (auto-sends confirmations).

## Run locally

### 1) Start Temporal dev server
```bash
temporal server start-dev
```

### 2) Install dependencies
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 3) Start worker
```bash
PYTHONPATH=src python -m workflow.run_worker
```

### 4) Run demo (in another terminal)
```bash
PYTHONPATH=src python -m workflow.run_demo
```

You should see a printed result with the final workflow state.

## Notes
- The workflow will wait for confirmation signals; in a real system you would add timeouts or escalation.
- Temporal workflows must be deterministic. Any non-deterministic work (LLM calls, HTTP) should live in activities.

---

## Workflow UI (shadcn/ui)

The UI lives in `frontend/` and uses **shadcn/ui-style components** (React + Tailwind).

### Run the UI
```bash
cd frontend
npm install
npm run dev
```

### What you get
- Single “工作流操作台” page
- 中文界面
- 画布区 + 右侧参数/配置 + 底部日志

---

## Backend API (Node + Express demo)

The backend lives in `backend/` and provides a minimal in-memory API.

### Run the backend
```bash
cd backend
npm install
npm run dev
```

### API list
- `GET /api/workflows` 工作流列表
- `GET /api/workflows/:id` 工作流详情
- `GET /api/workflows/:id/logs` 运行日志
- `POST /api/workflows/:id/run` 运行工作流
- `POST /api/workflows/:id/save` 保存参数/配置
