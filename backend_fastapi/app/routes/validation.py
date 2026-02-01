"""Graph validation and node type registry endpoints."""

from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from workflow.nodes.registry import list_node_types

from ..database import get_session
from ..repository import WorkflowRepository
from ..schemas import (
    GraphDefinitionRequest,
    NodeTypeResponse,
    ValidationErrorResponse,
    ValidationResponse,
)
from .workflows import _build_workflow_definition, _parse_graph_definition, validate_workflow_graph

router = APIRouter(tags=["validation"])


@router.get("/api/v2/node-types", response_model=List[NodeTypeResponse])
def get_node_types():
    """List all registered node types for the frontend palette."""
    definitions = list_node_types()
    return [
        NodeTypeResponse(
            node_type=d.node_type,
            display_name=d.display_name,
            description=d.description,
            category=d.category,
            input_schema=d.input_schema,
            output_schema=d.output_schema,
            icon=d.icon,
            color=d.color,
        )
        for d in definitions
    ]


@router.post(
    "/api/v2/workflows/{workflow_id}/validate",
    response_model=ValidationResponse,
)
async def validate_workflow_endpoint(
    workflow_id: str,
    session: AsyncSession = Depends(get_session),
):
    """Validate the current graph of a workflow."""
    repo = WorkflowRepository(session)
    workflow = await repo.get(workflow_id)
    if not workflow:
        raise HTTPException(status_code=404, detail="工作流不存在")

    if not workflow.graph_definition:
        raise HTTPException(status_code=400, detail="工作流尚无图定义")

    try:
        wf_def = _build_workflow_definition(workflow.graph_definition)
        result = validate_workflow_graph(wf_def)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    return ValidationResponse(
        valid=result.valid,
        errors=[
            ValidationErrorResponse(**err.to_dict()) for err in result.errors
        ],
        warnings=[
            ValidationErrorResponse(**warn.to_dict()) for warn in result.warnings
        ],
    )


@router.post("/api/v2/validate-graph", response_model=ValidationResponse)
async def validate_graph_inline(payload: GraphDefinitionRequest):
    """Validate a graph definition without saving (for live editor feedback)."""
    graph_dict = _parse_graph_definition(payload)
    try:
        wf_def = _build_workflow_definition(graph_dict)
        result = validate_workflow_graph(wf_def)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    return ValidationResponse(
        valid=result.valid,
        errors=[
            ValidationErrorResponse(**err.to_dict()) for err in result.errors
        ],
        warnings=[
            ValidationErrorResponse(**warn.to_dict()) for warn in result.warnings
        ],
    )
