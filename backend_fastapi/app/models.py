from __future__ import annotations

from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, Field


class WorkflowParameters(BaseModel):
    trigger: str
    priority: str = Field("normal", description="low|normal|high")
    schedule: str
    notifyBot: bool = True


class WorkflowSummary(BaseModel):
    id: str
    name: str
    status: str
    version: str
    created_at: str
    updated_at: str


class WorkflowDetail(WorkflowSummary):
    parameters: WorkflowParameters
    nodeConfig: str


class WorkflowLog(BaseModel):
    id: str
    runId: str
    time: str
    level: str
    message: str
    source: str


class RunRecord(BaseModel):
    id: str
    workflowId: str
    status: str
    started_at: str
    ended_at: Optional[str] = None
    triggered_by: str


class RunRequest(BaseModel):
    request: Optional[str] = None
    parameters: Optional[WorkflowParameters] = None
    clientRequestId: Optional[str] = None


class RunResponse(BaseModel):
    runId: str
    status: str


class SaveRequest(BaseModel):
    parameters: WorkflowParameters
    nodeConfig: Optional[str] = None
    clientRequestId: Optional[str] = None


class SaveResponse(BaseModel):
    message: str
    workflow: WorkflowDetail


class PagedLogs(BaseModel):
    items: List[WorkflowLog]
    page: int
    pageSize: int
    total: int


class PagedRuns(BaseModel):
    items: List[RunRecord]
    page: int
    pageSize: int
    total: int


class ConfirmRequest(BaseModel):
    stage: str = Field(..., description="initial|final")
    approved: bool
    feedback: str = ""


class ConfirmResponse(BaseModel):
    message: str
    runId: str
    stage: str


# === Graph Visualization Models ===


class GraphNodeData(BaseModel):
    label: str
    status: str = "pending"  # pending | running | completed | failed


class GraphNode(BaseModel):
    id: str
    type: str = "agentNode"
    data: GraphNodeData
    position: dict = Field(default_factory=lambda: {"x": 0, "y": 0})


class GraphEdge(BaseModel):
    id: str
    source: str
    target: str


class WorkflowGraph(BaseModel):
    nodes: List[GraphNode]
    edges: List[GraphEdge]


class NodeStatus(BaseModel):
    node: str
    status: str  # pending | running | completed | failed
    timestamp: str
    output: Optional[str] = None
    progress: Optional[int] = None


def now_iso() -> str:
    return datetime.utcnow().isoformat() + "Z"
