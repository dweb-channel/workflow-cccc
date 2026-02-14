"""SQLAlchemy ORM models for the workflow platform.

Tables:
- workflows: Workflow definitions with graph configuration
- workflow_runs: Execution records for each workflow run
- execution_logs: Detailed logs for each run
- node_executions: Per-node execution records within a run
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.sqlite import JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _gen_uuid() -> str:
    return str(uuid.uuid4())


# ─── Workflow Definition ─────────────────────────────────────────────


class WorkflowModel(Base):
    """Persistent workflow definition.

    Stores the full graph configuration (nodes + edges) as JSON,
    along with metadata like name, version, and status.
    """

    __tablename__ = "workflows"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_gen_uuid)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="draft",
        comment="draft | published | archived",
    )
    version: Mapped[str] = mapped_column(String(32), nullable=False, default="v1.0")

    # Graph definition stored as JSON
    graph_definition: Mapped[Optional[Dict[str, Any]]] = mapped_column(
        JSON, nullable=True, comment="WorkflowDefinition JSON: {nodes, edges, entry_point}",
    )

    # Parameters / configuration
    parameters: Mapped[Optional[Dict[str, Any]]] = mapped_column(
        JSON, nullable=True, comment="Default workflow parameters",
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow,
    )

    # Relationships
    runs: Mapped[List["WorkflowRunModel"]] = relationship(
        back_populates="workflow", cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index("ix_workflows_status", "status"),
        Index("ix_workflows_updated_at", "updated_at"),
    )


# ─── Workflow Run ────────────────────────────────────────────────────


class WorkflowRunModel(Base):
    """Record of a single workflow execution.

    Tracks run status, timing, input/output, and links to per-node executions.
    """

    __tablename__ = "workflow_runs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_gen_uuid)
    workflow_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("workflows.id", ondelete="CASCADE"), nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="pending",
        comment="pending | running | completed | failed | cancelled",
    )
    triggered_by: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)

    # Temporal integration
    temporal_workflow_id: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True, comment="Temporal workflow execution ID",
    )
    temporal_run_id: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True, comment="Temporal run ID",
    )

    # Input / output
    input_data: Mapped[Optional[Dict[str, Any]]] = mapped_column(
        JSON, nullable=True, comment="Run input parameters",
    )
    output_data: Mapped[Optional[Dict[str, Any]]] = mapped_column(
        JSON, nullable=True, comment="Final run output",
    )
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow,
    )
    ended_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )

    # Relationships
    workflow: Mapped["WorkflowModel"] = relationship(back_populates="runs")
    node_executions: Mapped[List["NodeExecutionModel"]] = relationship(
        back_populates="run", cascade="all, delete-orphan",
    )
    logs: Mapped[List["ExecutionLogModel"]] = relationship(
        back_populates="run", cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index("ix_runs_workflow_id", "workflow_id"),
        Index("ix_runs_status", "status"),
        Index("ix_runs_started_at", "started_at"),
    )


# ─── Node Execution ─────────────────────────────────────────────────


class NodeExecutionModel(Base):
    """Per-node execution record within a workflow run.

    Tracks individual node status, timing, input/output, and execution order.
    """

    __tablename__ = "node_executions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_gen_uuid)
    run_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("workflow_runs.id", ondelete="CASCADE"), nullable=False,
    )
    node_id: Mapped[str] = mapped_column(
        String(128), nullable=False, comment="Node ID within the workflow graph",
    )
    node_type: Mapped[str] = mapped_column(
        String(64), nullable=False, comment="Node type from registry",
    )
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="pending",
        comment="pending | running | completed | failed | skipped",
    )
    execution_order: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0,
    )

    # Input / output
    input_data: Mapped[Optional[Dict[str, Any]]] = mapped_column(
        JSON, nullable=True,
    )
    output_data: Mapped[Optional[Dict[str, Any]]] = mapped_column(
        JSON, nullable=True,
    )
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Timing
    started_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    ended_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    duration_ms: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True, comment="Execution duration in milliseconds",
    )

    # Relationship
    run: Mapped["WorkflowRunModel"] = relationship(back_populates="node_executions")

    __table_args__ = (
        Index("ix_node_exec_run_id", "run_id"),
        Index("ix_node_exec_node_id", "node_id"),
        Index("ix_node_exec_status", "status"),
    )


# ─── Execution Log ──────────────────────────────────────────────────


class ExecutionLogModel(Base):
    """Detailed execution log entries.

    Stores structured log messages from workflow execution,
    supporting filtering by level, source, and time range.
    """

    __tablename__ = "execution_logs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_gen_uuid)
    run_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("workflow_runs.id", ondelete="CASCADE"), nullable=False,
    )
    node_id: Mapped[Optional[str]] = mapped_column(
        String(128), nullable=True, comment="Associated node ID (null for workflow-level logs)",
    )
    level: Mapped[str] = mapped_column(
        String(16), nullable=False, default="info",
        comment="debug | info | warning | error",
    )
    message: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(
        String(64), nullable=False, default="system",
        comment="system | worker | api | node",
    )
    extra_data: Mapped[Optional[Dict[str, Any]]] = mapped_column(
        JSON, nullable=True, comment="Additional structured log data",
    )
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow,
    )

    # Relationship
    run: Mapped["WorkflowRunModel"] = relationship(back_populates="logs")

    __table_args__ = (
        Index("ix_logs_run_id", "run_id"),
        Index("ix_logs_level", "level"),
        Index("ix_logs_timestamp", "timestamp"),
        Index("ix_logs_node_id", "node_id"),
    )


# ─── Workspace ───────────────────────────────────────────────────────


class WorkspaceModel(Base):
    """Workspace groups batch jobs by repository."""

    __tablename__ = "workspaces"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_gen_uuid)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    repo_path: Mapped[str] = mapped_column(String(1024), nullable=False, unique=True)
    config_defaults: Mapped[Optional[Dict[str, Any]]] = mapped_column(
        JSON, nullable=True,
        comment="Default config inherited by new jobs: validation_level, failure_policy, max_retries, cwd",
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow,
    )
    last_used_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )

    # Relationships (no cascade delete — DB ondelete=SET NULL preserves jobs)
    jobs: Mapped[List["BatchJobModel"]] = relationship(
        back_populates="workspace",
    )

    __table_args__ = (
        Index("ix_workspaces_name", "name"),
        Index("ix_workspaces_last_used", "last_used_at"),
    )


# ─── Batch Bug Fix Job ───────────────────────────────────────────────


class BatchJobModel(Base):
    """Batch bug fix job record.

    Stores batch job metadata and configuration.
    Individual bug results are stored in BugResultModel.
    """

    __tablename__ = "batch_jobs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # e.g., job_xxx
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="started",
        comment="started | running | completed | failed",
    )
    workspace_id: Mapped[Optional[str]] = mapped_column(
        String(64), ForeignKey("workspaces.id", ondelete="SET NULL"), nullable=True,
    )
    target_group_id: Mapped[str] = mapped_column(String(128), nullable=False)
    fixer_peer_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    verifier_peer_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)

    # Config as JSON
    config: Mapped[Optional[Dict[str, Any]]] = mapped_column(
        JSON, nullable=True, comment="Job config: validation_level, failure_policy, max_retries",
    )

    # Error message if failed
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow,
    )

    # Relationships
    workspace: Mapped[Optional["WorkspaceModel"]] = relationship(back_populates="jobs")
    bugs: Mapped[List["BugResultModel"]] = relationship(
        back_populates="job", cascade="all, delete-orphan",
        order_by="BugResultModel.bug_index",
    )

    __table_args__ = (
        Index("ix_batch_jobs_status", "status"),
        Index("ix_batch_jobs_target_group", "target_group_id"),
        Index("ix_batch_jobs_created_at", "created_at"),
        Index("ix_batch_jobs_workspace_id", "workspace_id"),
    )


class BugResultModel(Base):
    """Individual bug result within a batch job."""

    __tablename__ = "bug_results"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_gen_uuid)
    job_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("batch_jobs.id", ondelete="CASCADE"), nullable=False,
    )
    bug_index: Mapped[int] = mapped_column(Integer, nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="pending",
        comment="pending | in_progress | completed | failed | skipped",
    )
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    started_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )

    # Execution steps as JSON array
    # Each step: {step, label, status, started_at, completed_at, duration_ms, output_preview, error, attempt}
    steps: Mapped[Optional[List[Dict[str, Any]]]] = mapped_column(
        JSON, nullable=True,
        comment="Execution steps: [{step, label, status, started_at, completed_at, duration_ms, output_preview, error}]",
    )

    # Relationship
    job: Mapped["BatchJobModel"] = relationship(back_populates="bugs")

    __table_args__ = (
        Index("ix_bug_results_job_id", "job_id"),
        Index("ix_bug_results_status", "status"),
    )


# ─── Design-to-Code Job ─────────────────────────────────────────────


class DesignJobModel(Base):
    """Design-to-code pipeline job record.

    Tracks design-to-code conversion jobs including status, component
    progress counters, and pipeline result summary.
    """

    __tablename__ = "design_jobs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # e.g., design_xxx
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="started",
        comment="started | running | completed | failed | cancelled",
    )
    design_file: Mapped[str] = mapped_column(
        Text, nullable=False, comment="Absolute path to design_export.json",
    )
    output_dir: Mapped[str] = mapped_column(
        Text, nullable=False, comment="Target directory for generated code",
    )
    cwd: Mapped[str] = mapped_column(
        Text, nullable=False, comment="Working directory for Claude CLI",
    )
    max_retries: Mapped[int] = mapped_column(
        Integer, nullable=False, default=2,
    )

    # Error message if failed
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Component progress counters
    components_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    components_completed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    components_failed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Pipeline result summary as JSON
    result: Mapped[Optional[Dict[str, Any]]] = mapped_column(
        JSON, nullable=True, comment="Pipeline result summary",
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow,
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )

    __table_args__ = (
        Index("ix_design_jobs_status", "status"),
        Index("ix_design_jobs_created_at", "created_at"),
    )
