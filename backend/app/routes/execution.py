"""Workflow execution and SSE streaming endpoints."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_session
from ..repositories.workflow import WorkflowRepository
from ..models.schemas import DynamicRunRequest, DynamicRunResponse
from ..event_bus import subscribe_events
from ..temporal_adapter import start_dynamic_workflow
from .workflows import _build_workflow_definition, validate_workflow_graph

router = APIRouter(prefix="/api/v2/workflows", tags=["execution"])


@router.post("/{workflow_id}/run", response_model=DynamicRunResponse)
async def run_dynamic_workflow(
    workflow_id: str,
    payload: Optional[DynamicRunRequest] = None,
    session: AsyncSession = Depends(get_session),
):
    """Run a dynamic workflow via Temporal."""
    repo = WorkflowRepository(session)
    workflow = await repo.get(workflow_id)
    if not workflow:
        raise HTTPException(status_code=404, detail="工作流不存在")

    if not workflow.graph_definition:
        raise HTTPException(status_code=400, detail="工作流尚无图定义，无法运行")

    if workflow.status == "archived":
        raise HTTPException(status_code=400, detail="已归档的工作流不能运行")

    # Validate graph before running
    try:
        wf_def = _build_workflow_definition(workflow.graph_definition)
        result = validate_workflow_graph(wf_def)
        if not result.valid:
            error_msgs = [e.message for e in result.errors]
            raise HTTPException(
                status_code=422,
                detail={"message": "图验证失败，无法运行", "errors": error_msgs},
            )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    # Build serializable workflow definition for Temporal
    wf_dict = {
        **workflow.graph_definition,
        "name": workflow.name,
    }

    initial_state = payload.initial_state if payload else {}

    try:
        run_id = await start_dynamic_workflow(
            workflow_definition=wf_dict,
            initial_state=initial_state,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=f"无法启动动态工作流: {exc}",
        ) from exc

    # Update workflow status
    await repo.update(workflow_id, status="running")

    return DynamicRunResponse(
        run_id=run_id,
        workflow_id=workflow_id,
        status="running",
    )


@router.get("/{workflow_id}/runs/{run_id}/stream")
async def stream_workflow_run(
    workflow_id: str,
    run_id: str,
    session: AsyncSession = Depends(get_session),
):
    """SSE endpoint for real-time workflow execution status."""
    repo = WorkflowRepository(session)
    workflow = await repo.get(workflow_id)
    if not workflow:
        raise HTTPException(status_code=404, detail="工作流不存在")

    return StreamingResponse(
        subscribe_events(run_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
