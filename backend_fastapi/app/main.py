from __future__ import annotations

import asyncio
import json
import sys
from contextlib import asynccontextmanager
from typing import List, Optional
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Query, Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

# Add parent directory to path for imports
sys.path.insert(0, str(__file__).rsplit("/app/", 1)[0])
from workflow.logging_config import get_sse_logger

logger = get_sse_logger()

from .models import (
    ConfirmRequest,
    ConfirmResponse,
    GraphEdge,
    GraphNode,
    GraphNodeData,
    PagedLogs,
    PagedRuns,
    RunRequest,
    RunResponse,
    SaveRequest,
    SaveResponse,
    WorkflowDetail,
    WorkflowGraph,
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


# === Graph Visualization Endpoints ===


def get_workflow_graph_topology() -> WorkflowGraph:
    """Return the current LangGraph node topology in React Flow format.

    This reflects the graph structure defined in workflow/graph.py
    """
    nodes = [
        GraphNode(
            id="parse_requirements",
            data=GraphNodeData(label="需求解析", status="pending"),
            position={"x": 100, "y": 100},
        ),
        GraphNode(
            id="peer1_plan",
            data=GraphNodeData(label="Peer1 规划", status="pending"),
            position={"x": 300, "y": 100},
        ),
        GraphNode(
            id="peer2_review",
            data=GraphNodeData(label="Peer2 审核", status="pending"),
            position={"x": 500, "y": 100},
        ),
        GraphNode(
            id="foreman_summary",
            data=GraphNodeData(label="Foreman 汇总", status="pending"),
            position={"x": 700, "y": 100},
        ),
        GraphNode(
            id="dispatch_tasks",
            data=GraphNodeData(label="任务分发", status="pending"),
            position={"x": 900, "y": 100},
        ),
    ]
    edges = [
        GraphEdge(id="e1", source="parse_requirements", target="peer1_plan"),
        GraphEdge(id="e2", source="peer1_plan", target="peer2_review"),
        GraphEdge(id="e3", source="peer2_review", target="foreman_summary"),
        GraphEdge(id="e4", source="foreman_summary", target="dispatch_tasks"),
    ]
    return WorkflowGraph(nodes=nodes, edges=edges)


@app.get("/api/workflows/{workflow_id}/graph", response_model=WorkflowGraph)
def get_workflow_graph(workflow_id: str):
    """Get the node topology for a workflow."""
    # Validate workflow exists
    workflow_exists = any(w.id == workflow_id for w in WORKFLOWS)
    if not workflow_exists:
        raise HTTPException(status_code=404, detail="未找到工作流")

    return get_workflow_graph_topology()


# Store active SSE connections for each run
_active_streams: dict[str, asyncio.Queue] = {}
# Buffer events before SSE connection is established
_event_buffers: dict[str, list] = {}


async def sse_event_generator(run_id: str):
    """Generate SSE events for a workflow run."""
    logger.info(f"🔗 Client connected for run_id: {run_id}")
    queue = asyncio.Queue()
    _active_streams[run_id] = queue

    try:
        # Send initial state
        graph = get_workflow_graph_topology()
        for node in graph.nodes:
            event_data = {
                "node": node.id,
                "status": "pending",
                "timestamp": now_iso(),
            }
            yield f"event: node_update\ndata: {json.dumps(event_data)}\n\n"

        # Flush any buffered events that arrived before SSE connection
        buffered = _event_buffers.pop(run_id, [])
        logger.info(f"📤 Flushing {len(buffered)} buffered events for {run_id}")
        for event in buffered:
            yield f"event: {event['event']}\ndata: {json.dumps(event['data'])}\n\n"

        # Stream updates from queue
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=30.0)
                if event is None:  # Sentinel to stop
                    break
                yield f"event: {event['event']}\ndata: {json.dumps(event['data'])}\n\n"

                # Check for workflow completion
                if event.get("event") == "workflow_complete":
                    break
            except asyncio.TimeoutError:
                # Send keepalive
                yield ": keepalive\n\n"
    finally:
        _active_streams.pop(run_id, None)
        _event_buffers.pop(run_id, None)  # Clean up any remaining buffer


@app.get("/api/workflows/{workflow_id}/runs/{run_id}/stream")
async def stream_workflow_run(
    workflow_id: str,
    run_id: str,
    demo: bool = Query(False, description="Enable demo mode with simulated events"),
):
    """SSE endpoint for real-time workflow execution status.

    Args:
        workflow_id: The workflow ID
        run_id: The run ID to stream
        demo: If True, simulate node execution for frontend development
    """
    # Validate workflow exists
    workflow_exists = any(w.id == workflow_id for w in WORKFLOWS)
    if not workflow_exists:
        raise HTTPException(status_code=404, detail="未找到工作流")

    if demo:
        return StreamingResponse(
            demo_sse_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    return StreamingResponse(
        sse_event_generator(run_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
        },
    )


async def demo_sse_generator():
    """Generate demo SSE events to simulate workflow execution."""
    nodes = ["parse_requirements", "peer1_plan", "peer2_review", "foreman_summary", "dispatch_tasks"]
    outputs = [
        "需求已解析: MVP focus with human confirmation checkpoints",
        "规划完成: 1) Define workflow nodes 2) Add confirmation 3) Implement Temporal",
        "审核通过: Plan is coherent for MVP, no blocking issues",
        "汇总完成: All peer outputs consolidated, ready for dispatch",
        "任务已分发: 3 tasks created and assigned",
    ]

    # Send initial pending state
    for node in nodes:
        event_data = {"node": node, "status": "pending", "timestamp": now_iso()}
        yield f"event: node_update\ndata: {json.dumps(event_data)}\n\n"

    await asyncio.sleep(0.5)

    # Simulate node execution
    for i, node in enumerate(nodes):
        # Node starts running
        event_data = {"node": node, "status": "running", "timestamp": now_iso()}
        yield f"event: node_update\ndata: {json.dumps(event_data)}\n\n"

        # Simulate some output
        await asyncio.sleep(1.0)
        output_data = {"node": node, "output": outputs[i], "timestamp": now_iso()}
        yield f"event: node_output\ndata: {json.dumps(output_data)}\n\n"

        # Node completes
        await asyncio.sleep(0.5)
        event_data = {"node": node, "status": "completed", "timestamp": now_iso()}
        yield f"event: node_update\ndata: {json.dumps(event_data)}\n\n"

    # Workflow complete
    complete_data = {"status": "success", "result": {"tasks": 3}, "timestamp": now_iso()}
    yield f"event: workflow_complete\ndata: {json.dumps(complete_data)}\n\n"


def push_node_event(run_id: str, event_type: str, data: dict):
    """Push an event to a running SSE stream.

    Called from workflow execution to update clients.
    If SSE connection not yet established, buffer events for later delivery.
    """
    event = {"event": event_type, "data": data}
    queue = _active_streams.get(run_id)
    if queue:
        queue.put_nowait(event)
        logger.info(f"📨 Event sent to queue: {event_type} for {run_id}")
    else:
        # Buffer events until SSE connection is established
        _event_buffers.setdefault(run_id, []).append(event)
        buffer_size = len(_event_buffers[run_id])
        logger.info(f"📦 Event buffered ({buffer_size}): {event_type} for {run_id}")


# === Internal API for Activity Callbacks ===


class InternalEventRequest(BaseModel):
    event_type: str
    data: dict


@app.post("/api/internal/events/{run_id}")
async def push_event_endpoint(run_id: str, payload: InternalEventRequest):
    """Internal endpoint for activities to push SSE events.

    Called by Temporal activities to update workflow execution status.
    """
    logger.info(f"📥 Received event via API: {payload.event_type} for {run_id}")
    push_node_event(run_id, payload.event_type, payload.data)
    return {"status": "ok", "run_id": run_id}
