"""Workflow CRUD API endpoints."""

from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from workflow.engine.graph_builder import (
    EdgeDefinition,
    NodeConfig,
    WorkflowDefinition,
    validate_workflow as validate_workflow_graph,
)

from ..database import get_session
from app.repositories.workflow import WorkflowRepository
from app.models.schemas import (
    CreateWorkflowRequest,
    GraphDefinitionRequest,
    PagedWorkflowsResponse,
    UpdateWorkflowRequest,
    WorkflowResponse,
)

router = APIRouter(prefix="/api/v2/workflows", tags=["workflows"])


# --- Helper functions ---


def _workflow_to_response(wf) -> WorkflowResponse:
    """Convert ORM WorkflowModel to API response."""
    return WorkflowResponse(
        id=wf.id,
        name=wf.name,
        description=wf.description,
        status=wf.status,
        version=wf.version,
        graph_definition=wf.graph_definition,
        parameters=wf.parameters,
        created_at=wf.created_at.isoformat() + "Z" if wf.created_at else "",
        updated_at=wf.updated_at.isoformat() + "Z" if wf.updated_at else "",
    )


def _parse_graph_definition(gd: GraphDefinitionRequest) -> dict:
    """Convert GraphDefinitionRequest to storable dict.

    Normalizes frontend format (data.config) to backend format (config).
    """
    nodes = []
    for n in gd.nodes:
        # Extract config from either format
        config = n.get_config()
        nodes.append({
            "id": n.id,
            "type": n.type,
            "config": config,
        })
    return {
        "nodes": nodes,
        "edges": [e.model_dump() for e in gd.edges],
        "entry_point": gd.entry_point,
    }


def _build_workflow_definition(graph_dict: dict) -> WorkflowDefinition:
    """Convert stored graph dict to WorkflowDefinition for validation."""
    nodes = [
        NodeConfig(id=n["id"], type=n["type"], config=n.get("config", {}))
        for n in graph_dict.get("nodes", [])
    ]
    edges = [
        EdgeDefinition(
            id=e["id"],
            source=e["source"],
            target=e["target"],
            condition=e.get("condition"),
        )
        for e in graph_dict.get("edges", [])
    ]
    return WorkflowDefinition(
        name="validation",
        nodes=nodes,
        edges=edges,
        entry_point=graph_dict.get("entry_point"),
    )


# --- CRUD Endpoints ---


@router.post("", response_model=WorkflowResponse, status_code=201)
async def create_workflow(
    payload: CreateWorkflowRequest,
    session: AsyncSession = Depends(get_session),
):
    """Create a new dynamic workflow."""
    repo = WorkflowRepository(session)

    graph_def = None
    if payload.graph_definition:
        graph_def = _parse_graph_definition(payload.graph_definition)

    workflow = await repo.create(
        name=payload.name,
        description=payload.description,
        graph_definition=graph_def,
        parameters=payload.parameters,
    )
    return _workflow_to_response(workflow)


@router.get("", response_model=PagedWorkflowsResponse)
async def list_dynamic_workflows(
    status: Optional[str] = Query(None, description="Filter by status"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    session: AsyncSession = Depends(get_session),
):
    """List dynamic workflows with pagination."""
    repo = WorkflowRepository(session)
    workflows, total = await repo.list(status=status, page=page, page_size=page_size)
    return PagedWorkflowsResponse(
        items=[_workflow_to_response(wf) for wf in workflows],
        page=page,
        page_size=page_size,
        total=total,
    )


@router.get("/{workflow_id}", response_model=WorkflowResponse)
async def get_dynamic_workflow(
    workflow_id: str,
    session: AsyncSession = Depends(get_session),
):
    """Get a single dynamic workflow by ID."""
    repo = WorkflowRepository(session)
    workflow = await repo.get(workflow_id)
    if not workflow:
        raise HTTPException(status_code=404, detail="工作流不存在")
    return _workflow_to_response(workflow)


@router.patch("/{workflow_id}", response_model=WorkflowResponse)
async def update_dynamic_workflow(
    workflow_id: str,
    payload: UpdateWorkflowRequest,
    session: AsyncSession = Depends(get_session),
):
    """Update workflow metadata (name, description, status, parameters)."""
    repo = WorkflowRepository(session)
    updates = {k: v for k, v in payload.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(status_code=400, detail="没有可更新的字段")

    if "status" in updates and updates["status"] not in ("draft", "published", "archived"):
        raise HTTPException(status_code=400, detail="status 必须是 draft/published/archived")

    workflow = await repo.update(workflow_id, **updates)
    if not workflow:
        raise HTTPException(status_code=404, detail="工作流不存在")
    return _workflow_to_response(workflow)


@router.put("/{workflow_id}/graph", response_model=WorkflowResponse)
async def update_workflow_graph(
    workflow_id: str,
    payload: GraphDefinitionRequest,
    session: AsyncSession = Depends(get_session),
):
    """Update workflow graph definition (nodes + edges)."""
    repo = WorkflowRepository(session)

    # Validate graph before saving
    graph_dict = _parse_graph_definition(payload)
    try:
        wf_def = _build_workflow_definition(graph_dict)
        result = validate_workflow_graph(wf_def)
        if not result.valid:
            error_msgs = [e.message for e in result.errors]
            raise HTTPException(
                status_code=422,
                detail={"message": "图验证失败", "errors": error_msgs},
            )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    workflow = await repo.update_graph(workflow_id, graph_dict)
    if not workflow:
        raise HTTPException(status_code=404, detail="工作流不存在")
    return _workflow_to_response(workflow)


@router.delete("/{workflow_id}", status_code=204)
async def delete_dynamic_workflow(
    workflow_id: str,
    session: AsyncSession = Depends(get_session),
):
    """Delete a workflow."""
    repo = WorkflowRepository(session)
    deleted = await repo.delete(workflow_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="工作流不存在")
