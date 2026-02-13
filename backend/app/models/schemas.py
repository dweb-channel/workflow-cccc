"""Pydantic request/response models for the workflow API."""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field


class NodeDataRequest(BaseModel):
    """Node data in frontend format (React Flow)."""
    label: Optional[str] = None
    config: dict = Field(default_factory=dict)


class NodeConfigRequest(BaseModel):
    """Node configuration in API request.

    Supports both formats:
    - Frontend (React Flow): node.data.label, node.data.config
    - Legacy: node.config directly
    """
    id: str
    type: str
    position: Optional[dict] = None
    # Frontend format (React Flow)
    data: Optional[NodeDataRequest] = None
    # Legacy format
    config: dict = Field(default_factory=dict)

    def get_config(self) -> dict:
        """Get config from either format."""
        if self.data and self.data.config:
            return self.data.config
        return self.config

    def get_label(self) -> str:
        """Get label from data or config.name."""
        if self.data and self.data.label:
            return self.data.label
        return self.config.get("name", "")


class EdgeRequest(BaseModel):
    """Edge definition in API request."""
    id: str
    source: str
    target: str
    condition: Optional[str] = None


class GraphDefinitionRequest(BaseModel):
    """Full graph definition for create/update."""
    nodes: List[NodeConfigRequest]
    edges: List[EdgeRequest]
    entry_point: Optional[str] = None


class CreateWorkflowRequest(BaseModel):
    """Request to create a new dynamic workflow."""
    name: str
    description: Optional[str] = None
    graph_definition: Optional[GraphDefinitionRequest] = None
    parameters: Optional[dict] = None


class UpdateWorkflowRequest(BaseModel):
    """Request to update workflow metadata."""
    name: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None
    parameters: Optional[dict] = None


class WorkflowResponse(BaseModel):
    """Workflow data in API response."""
    id: str
    name: str
    description: Optional[str]
    status: str
    version: str
    graph_definition: Optional[dict]
    parameters: Optional[dict]
    created_at: str
    updated_at: str


class PagedWorkflowsResponse(BaseModel):
    """Paginated workflow list."""
    items: List[WorkflowResponse]
    page: int
    page_size: int
    total: int


class NodeTypeResponse(BaseModel):
    """Node type definition for frontend palette."""
    node_type: str
    display_name: str
    description: str
    category: str
    input_schema: dict
    output_schema: dict
    icon: Optional[str] = None
    color: Optional[str] = None


class ValidationErrorResponse(BaseModel):
    """Single validation error/warning."""
    code: str
    message: str
    severity: str
    node_ids: List[str]
    context: dict


class ValidationResponse(BaseModel):
    """Graph validation result."""
    valid: bool
    errors: List[ValidationErrorResponse]
    warnings: List[ValidationErrorResponse]


class DynamicRunRequest(BaseModel):
    """Request to run a dynamic workflow."""
    initial_state: dict = Field(default_factory=dict, description="Initial input values")


class DynamicRunResponse(BaseModel):
    """Response after starting a dynamic workflow run."""
    run_id: str
    workflow_id: str
    status: str
