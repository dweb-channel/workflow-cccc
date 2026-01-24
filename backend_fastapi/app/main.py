from __future__ import annotations

from contextlib import asynccontextmanager
from typing import List, Optional
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from .models import (
    ConfirmRequest,
    ConfirmResponse,
    PagedLogs,
    PagedRuns,
    RunRequest,
    RunResponse,
    SaveRequest,
    SaveResponse,
    WorkflowDetail,
    WorkflowLog,
    WorkflowSummary,
    now_iso,
)
from .storage import LOGS, RUNS, WORKFLOWS
from .temporal_adapter import (
    close_temporal_client,
    init_temporal_client,
    send_confirm_signal,
    start_business_workflow,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage Temporal client lifecycle."""
    await init_temporal_client()
    yield
    await close_temporal_client()


app = FastAPI(title="工作流操作台 API", version="0.1.0", lifespan=lifespan)

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def paginate(items: List, page: int, page_size: int):
    start = (page - 1) * page_size
    end = start + page_size
    return items[start:end]


@app.get("/api/workflows", response_model=List[WorkflowSummary])
def list_workflows():
    return [
        WorkflowSummary(**workflow.model_dump())
        for workflow in WORKFLOWS
    ]


@app.get("/api/workflows/{workflow_id}", response_model=WorkflowDetail)
def get_workflow(workflow_id: str):
    for workflow in WORKFLOWS:
        if workflow.id == workflow_id:
            return workflow
    raise HTTPException(status_code=404, detail="未找到工作流")


@app.get("/api/workflows/{workflow_id}/runs", response_model=PagedRuns)
def list_runs(
    workflow_id: str,
    page: int = Query(1, ge=1),
    pageSize: int = Query(20, ge=1, le=100),
):
    runs = RUNS.get(workflow_id, [])
    return PagedRuns(items=paginate(runs, page, pageSize), page=page, pageSize=pageSize, total=len(runs))


@app.get("/api/workflows/{workflow_id}/logs", response_model=PagedLogs)
def get_logs(
    workflow_id: str,
    page: int = Query(1, ge=1),
    pageSize: int = Query(20, ge=1, le=100),
):
    logs = LOGS.get(workflow_id, [])
    return PagedLogs(items=paginate(logs, page, pageSize), page=page, pageSize=pageSize, total=len(logs))


@app.post("/api/workflows/{workflow_id}/run", response_model=RunResponse)
async def run_workflow(workflow_id: str, payload: Optional[RunRequest] = None):
    for workflow in WORKFLOWS:
        if workflow.id == workflow_id:
            workflow.status = "running"
            workflow.updated_at = now_iso()
            request_text = payload.request if payload and payload.request else f"运行工作流 {workflow.id}"
            try:
                run_id = await start_business_workflow(request_text)
            except Exception as exc:
                raise HTTPException(
                    status_code=503,
                    detail=f"无法连接 Temporal 或启动 workflow: {exc}",
                ) from exc

            RUNS.setdefault(workflow.id, []).insert(
                0,
                {
                    "id": run_id,
                    "workflowId": workflow.id,
                    "status": "running",
                    "started_at": now_iso(),
                    "ended_at": None,
                    "triggered_by": workflow.parameters.trigger,
                },
            )
            LOGS.setdefault(workflow.id, []).insert(
                0,
                {
                    "id": str(uuid4()),
                    "runId": run_id,
                    "time": now_iso(),
                    "level": "info",
                    "message": "启动运行",
                    "source": "api",
                },
            )
            return RunResponse(runId=run_id, status=workflow.status)
    raise HTTPException(status_code=404, detail="未找到工作流")


@app.post("/api/workflows/{workflow_id}/save", response_model=SaveResponse)
def save_workflow(workflow_id: str, payload: SaveRequest):
    for workflow in WORKFLOWS:
        if workflow.id == workflow_id:
            workflow.parameters = payload.parameters
            if payload.nodeConfig is not None:
                workflow.nodeConfig = payload.nodeConfig
            workflow.updated_at = now_iso()
            return SaveResponse(message="保存成功", workflow=workflow)
    raise HTTPException(status_code=404, detail="未找到工作流")


@app.post(
    "/api/workflows/{workflow_id}/runs/{run_id}/confirm",
    response_model=ConfirmResponse,
)
async def confirm_workflow(
    workflow_id: str,
    run_id: str,
    payload: ConfirmRequest,
):
    """Send confirmation signal to a running workflow.

    Args:
        workflow_id: The workflow ID
        run_id: The Temporal run ID
        payload: Confirmation details (stage, approved, feedback)
    """
    # Validate workflow exists
    workflow_exists = any(w.id == workflow_id for w in WORKFLOWS)
    if not workflow_exists:
        raise HTTPException(status_code=404, detail="未找到工作流")

    # Validate stage
    if payload.stage not in ("initial", "final"):
        raise HTTPException(
            status_code=400,
            detail="stage 必须是 'initial' 或 'final'",
        )

    try:
        await send_confirm_signal(
            run_id=run_id,
            stage=payload.stage,
            approved=payload.approved,
            feedback=payload.feedback,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=f"无法发送确认信号: {exc}",
        ) from exc

    # Log the confirmation
    action = "批准" if payload.approved else "拒绝"
    stage_cn = "初始确认" if payload.stage == "initial" else "最终确认"
    LOGS.setdefault(workflow_id, []).insert(
        0,
        {
            "id": str(uuid4()),
            "runId": run_id,
            "time": now_iso(),
            "level": "info",
            "message": f"{stage_cn}: {action}",
            "source": "api",
        },
    )

    return ConfirmResponse(
        message=f"{stage_cn}信号已发送",
        runId=run_id,
        stage=payload.stage,
    )
