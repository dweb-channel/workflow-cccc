"""Batch Bug Fix and Jira Integration API endpoints.

Provides endpoints for dispatching batch bug fix tasks and querying Jira.
Workflow execution is delegated to Temporal Worker (separate process).
SSE events arrive via the shared /api/internal/events/{run_id} endpoint.
"""

from __future__ import annotations

import json
import logging
import os
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator

# Database imports
from app.database import get_session_ctx
from app.batch_job_repository import BatchJobRepository
from app.db_models import BatchJobModel, BugResultModel

# SSE infrastructure (shared with generic workflow execution)
from app.sse import sse_event_generator, push_node_event

# Temporal client (lazy import to avoid startup dependency)
from app.temporal_adapter import get_client
from workflow.config import TASK_QUEUE

logger = logging.getLogger("workflow.routes.batch")

router = APIRouter(prefix="/api/v2/batch", tags=["batch"])

# No in-memory workflow handles — use Temporal client to get handles by ID.
# This survives FastAPI restarts (workflow ID = "batch-{job_id}").


# --- Schemas ---


class BatchBugFixConfig(BaseModel):
    """Configuration for batch bug fix job."""
    validation_level: Literal["minimal", "standard", "thorough"] = "standard"
    failure_policy: Literal["stop", "skip", "retry"] = "skip"
    max_retries: int = Field(default=3, ge=1, le=10)


class BatchBugFixRequest(BaseModel):
    """Request for POST /api/v2/batch/bug-fix."""
    jira_urls: List[str] = Field(..., min_length=1, description="List of Jira bug URLs")
    cwd: Optional[str] = Field(
        None,
        description="Working directory for Claude CLI (defaults to current directory)",
    )
    config: Optional[BatchBugFixConfig] = None

    @field_validator("jira_urls")
    @classmethod
    def validate_jira_urls(cls, urls: List[str]) -> List[str]:
        """Validate that each URL is a reachable Jira-like URL.

        Rejects:
        - Non-HTTP(S) URLs
        - Reserved/example domains (example.com, localhost, etc.)
        - Malformed URLs without proper host
        """
        _BLOCKED_HOSTS = {"example.com", "example.org", "example.net", "localhost", "127.0.0.1"}

        invalid = []
        for url in urls:
            url = url.strip()
            if not url:
                invalid.append(("(empty)", "URL cannot be empty"))
                continue
            parsed = urlparse(url)
            if parsed.scheme not in ("http", "https"):
                invalid.append((url, f"must use http or https (got '{parsed.scheme}')"))
                continue
            host = (parsed.hostname or "").lower()
            if not host:
                invalid.append((url, "missing hostname"))
                continue
            # Check blocked domains (exact match or subdomain)
            base_host = ".".join(host.rsplit(".", 2)[-2:]) if "." in host else host
            if base_host in _BLOCKED_HOSTS or host in _BLOCKED_HOSTS:
                invalid.append((url, f"'{host}' is a reserved/example domain, not a real Jira instance"))
                continue

        if invalid:
            details = "; ".join(f"{u}: {reason}" for u, reason in invalid)
            raise ValueError(f"Invalid Jira URL(s): {details}")
        return urls


class BugStepInfo(BaseModel):
    """Execution step information for a bug."""
    step: str
    label: str
    status: Literal["pending", "in_progress", "completed", "failed"] = "pending"
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    duration_ms: Optional[float] = None
    output_preview: Optional[str] = None
    error: Optional[str] = None
    attempt: Optional[int] = None


class BugStatus(BaseModel):
    """Status of a single bug in the batch."""
    url: str
    status: Literal["pending", "in_progress", "completed", "failed", "skipped"]
    error: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    steps: Optional[List[BugStepInfo]] = None
    retry_count: Optional[int] = None


class BatchBugFixResponse(BaseModel):
    """Response for POST /api/v2/batch/bug-fix."""
    job_id: str
    status: Literal["started", "running", "completed", "failed", "cancelled"]
    total_bugs: int
    created_at: str


class BatchJobStatusResponse(BaseModel):
    """Response for GET /api/v2/batch/bug-fix/{job_id}."""
    job_id: str
    status: Literal["started", "running", "completed", "failed", "cancelled"]
    total_bugs: int
    completed: int
    failed: int
    skipped: int
    in_progress: int
    pending: int
    bugs: List[BugStatus]
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class BatchJobSummary(BaseModel):
    """Summary of a batch job for list view."""
    job_id: str
    status: Literal["started", "running", "completed", "failed", "cancelled"]
    total_bugs: int
    completed: int
    failed: int
    created_at: str
    updated_at: str


class BatchJobListResponse(BaseModel):
    """Response for GET /api/v2/batch/bug-fix (list)."""
    jobs: List[BatchJobSummary]
    total: int
    page: int
    page_size: int


# --- Batch Bug Fix Endpoints ---


@router.post("/bug-fix", response_model=BatchBugFixResponse, status_code=201)
async def create_batch_bug_fix(payload: BatchBugFixRequest):
    """Start a batch bug fix job.

    Dispatches bug fix tasks to Temporal Worker via BatchBugFixWorkflow.
    Returns a job_id for tracking progress.
    """
    # Generate job ID
    job_id = f"job_{uuid.uuid4().hex[:12]}"
    now = datetime.now(timezone.utc).isoformat()
    cwd = payload.cwd or "."

    # Create job record
    config = payload.config or BatchBugFixConfig()

    # Save to database
    async with get_session_ctx() as session:
        repo = BatchJobRepository(session)
        await repo.create(
            job_id=job_id,
            target_group_id="",
            jira_urls=payload.jira_urls,
            fixer_peer_id="",
            verifier_peer_id="",
            config=config.model_dump(),
        )
        logger.info(f"Job {job_id}: Saved to database")

    # Start Temporal workflow (runs in separate Worker process)
    try:
        client = await get_client()
        workflow_params = {
            "job_id": job_id,
            "jira_urls": payload.jira_urls,
            "cwd": cwd,
            "config": config.model_dump(),
        }
        await client.start_workflow(
            "BatchBugFixWorkflow",
            workflow_params,
            id=f"batch-{job_id}",
            task_queue=TASK_QUEUE,
        )
        logger.info(f"Job {job_id}: Temporal workflow started (id=batch-{job_id})")

    except Exception as e:
        logger.error(f"Job {job_id}: Failed to start Temporal workflow: {e}")
        try:
            async with get_session_ctx() as session:
                repo = BatchJobRepository(session)
                await repo.update_status(job_id, "failed", error=str(e))
        except Exception:
            pass
        raise HTTPException(
            status_code=503,
            detail=f"Failed to start workflow: {e}. Is Temporal running?",
        )

    return BatchBugFixResponse(
        job_id=job_id,
        status="started",
        total_bugs=len(payload.jira_urls),
        created_at=now,
    )


def _db_job_to_dict(db_job: BatchJobModel) -> Dict[str, Any]:
    """Convert database job model to dict format for API responses."""
    return {
        "job_id": db_job.id,
        "status": db_job.status,
        "config": db_job.config or {},
        "error": db_job.error,
        "bugs": [
            {
                "url": bug.url,
                "status": bug.status,
                "error": bug.error,
                "started_at": bug.started_at.isoformat() if bug.started_at else None,
                "completed_at": bug.completed_at.isoformat() if bug.completed_at else None,
                "steps": bug.steps,
                "retry_count": _count_retries(bug.steps),
            }
            for bug in sorted(db_job.bugs, key=lambda b: b.bug_index)
        ],
        "created_at": db_job.created_at.isoformat() if db_job.created_at else "",
        "updated_at": db_job.updated_at.isoformat() if db_job.updated_at else "",
    }


def _count_retries(steps: Optional[List[Dict[str, Any]]]) -> int:
    """Count the number of retries from steps data."""
    if not steps:
        return 0
    max_attempt = 0
    for step in steps:
        attempt = step.get("attempt")
        if attempt is not None and attempt > max_attempt:
            max_attempt = attempt
    return max(0, max_attempt - 1)  # attempt 1 = first try, not a retry


@router.get("/bug-fix/{job_id}", response_model=BatchJobStatusResponse)
async def get_batch_bug_fix_status(job_id: str):
    """Get the status of a batch bug fix job."""
    async with get_session_ctx() as session:
        repo = BatchJobRepository(session)
        db_job = await repo.get(job_id)

    if not db_job:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")

    job = _db_job_to_dict(db_job)
    bugs = job.get("bugs", [])

    # Calculate counts
    completed = sum(1 for b in bugs if b["status"] == "completed")
    failed = sum(1 for b in bugs if b["status"] == "failed")
    in_progress = sum(1 for b in bugs if b["status"] == "in_progress")
    pending = sum(1 for b in bugs if b["status"] == "pending")
    skipped = sum(1 for b in bugs if b["status"] == "skipped")

    # Determine overall status
    if in_progress > 0:
        status = "running"
    elif pending > 0 and (completed > 0 or failed > 0):
        status = "running"
    elif pending == 0 and in_progress == 0:
        status = "completed" if failed == 0 else "failed"
    else:
        status = job.get("status", "started")

    return BatchJobStatusResponse(
        job_id=job_id,
        status=status,
        total_bugs=len(bugs),
        completed=completed,
        failed=failed,
        skipped=skipped,
        in_progress=in_progress,
        pending=pending,
        bugs=[BugStatus(**b) for b in bugs],
        created_at=job.get("created_at", ""),
        updated_at=job.get("updated_at", ""),
    )


@router.get("/bug-fix", response_model=BatchJobListResponse)
async def list_batch_bug_fix_jobs(
    status: Optional[str] = Query(None, description="Filter by job status"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page"),
):
    """List batch bug fix jobs with pagination."""
    async with get_session_ctx() as session:
        repo = BatchJobRepository(session)
        jobs, total = await repo.list(
            status=status,
            page=page,
            page_size=page_size,
        )

        job_summaries = []
        for db_job in jobs:
            stats = {s: 0 for s in ["completed", "failed", "skipped", "in_progress", "pending"]}
            for bug in db_job.bugs:
                if bug.status in stats:
                    stats[bug.status] += 1

            job_summaries.append(BatchJobSummary(
                job_id=db_job.id,
                status=db_job.status,
                total_bugs=len(db_job.bugs),
                completed=stats["completed"],
                failed=stats["failed"] + stats["skipped"],
                created_at=db_job.created_at.isoformat() if db_job.created_at else "",
                updated_at=db_job.updated_at.isoformat() if db_job.updated_at else "",
            ))

        return BatchJobListResponse(
            jobs=job_summaries,
            total=total,
            page=page,
            page_size=page_size,
        )


# --- SSE Progress Streaming ---


async def _batch_sse_generator(job_id: str):
    """SSE generator for batch job progress.

    Sends initial job state from DB, then streams real-time events
    from the shared SSE infrastructure (events arrive from Temporal
    Worker via HTTP POST to /api/internal/events/{job_id}).
    """
    # Send initial job state from database
    try:
        async with get_session_ctx() as session:
            repo = BatchJobRepository(session)
            db_job = await repo.get(job_id)
        if db_job:
            initial_state = _db_job_to_dict(db_job)
            yield f"event: job_state\ndata: {json.dumps(initial_state, default=str)}\n\n"
    except Exception as e:
        logger.error(f"Job {job_id}: Failed to send initial SSE state: {e}")

    # Stream events from shared SSE infrastructure.
    # sse_event_generator creates a queue in _active_streams[job_id]
    # that receives events pushed to /api/internal/events/{job_id}.
    # It stops on "workflow_complete"; we also stop on "job_done".
    async for event_str in sse_event_generator(job_id):
        yield event_str
        # Check if this is a job_done event (batch-specific stop signal)
        if "job_done" in event_str and event_str.startswith("event:"):
            break


@router.get("/bug-fix/{job_id}/stream")
async def stream_batch_job_progress(job_id: str):
    """Stream real-time progress updates for a batch bug fix job via SSE.

    Events:
    - job_state: Initial job state when connected
    - bug_started: When a bug fix starts (data: {bug_index, url})
    - bug_step_started: When a step begins (data: {bug_index, step, label, attempt?})
    - bug_step_completed: When a step completes (data: {bug_index, step, label, status, ...})
    - bug_completed: When a bug fix completes (data: {bug_index, url})
    - bug_failed: When a bug fix fails (data: {bug_index, url, error})
    - ai_thinking: Real-time AI execution events (data: {node_id, bug_index, type, ...})
    - job_done: When the entire job completes (data: {status, completed, failed})

    Usage:
        const sse = new EventSource('/api/v2/batch/bug-fix/job_xxx/stream');
        sse.addEventListener('bug_step_started', (e) => console.log(JSON.parse(e.data)));
    """
    # Verify job exists in database
    async with get_session_ctx() as session:
        repo = BatchJobRepository(session)
        db_job = await repo.get(job_id)

    if not db_job:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")

    return StreamingResponse(
        _batch_sse_generator(job_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# --- Job Control Endpoints ---


class JobControlResponse(BaseModel):
    """Response for job control operations (cancel/pause/resume)."""
    success: bool
    job_id: str
    status: str
    message: str


@router.post("/bug-fix/{job_id}/cancel", response_model=JobControlResponse)
async def cancel_batch_job(job_id: str):
    """Cancel a running batch bug fix job.

    Cancels the Temporal workflow and marks the job as cancelled.
    Bugs that were in progress will be marked as failed.
    """
    # Check database
    async with get_session_ctx() as session:
        repo = BatchJobRepository(session)
        db_job = await repo.get(job_id)

    if not db_job:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")

    if db_job.status in ["completed", "failed", "cancelled"]:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot cancel job with status '{db_job.status}'"
        )

    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()

    # Cancel the Temporal workflow via client lookup (survives server restarts)
    try:
        client = await get_client()
        handle = client.get_workflow_handle(f"batch-{job_id}")
        await handle.cancel()
        logger.info(f"Job {job_id}: Temporal workflow cancelled")
    except Exception as e:
        logger.warning(f"Job {job_id}: Failed to cancel Temporal workflow: {e}")

    # Update database
    try:
        async with get_session_ctx() as session:
            repo = BatchJobRepository(session)
            await repo.update_status(job_id, "cancelled")
            db_job = await repo.get(job_id)
            if db_job:
                for bug in db_job.bugs:
                    if bug.status == "in_progress":
                        await repo.update_bug_status(
                            job_id=job_id,
                            bug_index=bug.bug_index,
                            status="failed",
                            error="Job cancelled",
                            completed_at=now,
                        )
        logger.info(f"Job {job_id}: Status updated to cancelled in database")
    except Exception as e:
        logger.error(f"Job {job_id}: Failed to update database: {e}")

    # Push SSE event so connected clients know the job is done
    push_node_event(job_id, "job_done", {
        "status": "cancelled",
        "message": "Job cancelled by user",
        "timestamp": now_iso,
    })

    return JobControlResponse(
        success=True,
        job_id=job_id,
        status="cancelled",
        message="Job cancelled successfully",
    )


@router.delete("/bug-fix/{job_id}", response_model=JobControlResponse)
async def delete_batch_job(job_id: str):
    """Delete a batch job and all its bug results.

    Running jobs will be cancelled first, then deleted.
    """
    # Cancel Temporal workflow if still running (lookup by ID, survives restarts)
    try:
        client = await get_client()
        handle = client.get_workflow_handle(f"batch-{job_id}")
        await handle.cancel()
    except Exception:
        pass  # Workflow may already be completed/cancelled

    # Delete from database
    try:
        async with get_session_ctx() as session:
            repo = BatchJobRepository(session)
            deleted = await repo.delete(job_id)
            if not deleted:
                raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete job {job_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Delete failed: {e}")

    logger.info(f"Job {job_id}: Deleted successfully")
    return JobControlResponse(
        success=True,
        job_id=job_id,
        status="deleted",
        message="Job deleted successfully",
    )


class BatchDeleteRequest(BaseModel):
    """Request for batch deletion."""
    job_ids: List[str] = Field(..., description="List of job IDs to delete")


class BatchDeleteResponse(BaseModel):
    """Response for batch deletion."""
    deleted: List[str]
    failed: List[str]
    message: str


@router.post("/bug-fix/batch-delete", response_model=BatchDeleteResponse)
async def batch_delete_jobs(request: BatchDeleteRequest):
    """Delete multiple batch jobs at once."""
    deleted = []
    failed = []
    for job_id in request.job_ids:
        try:
            await delete_batch_job(job_id)
            deleted.append(job_id)
        except Exception:
            failed.append(job_id)

    return BatchDeleteResponse(
        deleted=deleted,
        failed=failed,
        message=f"Deleted {len(deleted)}/{len(request.job_ids)} jobs",
    )


# --- Metrics Endpoints ---


@router.get("/metrics/job/{job_id}")
async def get_job_metrics(job_id: str):
    """Get detailed metrics for a single batch job.

    Returns timing stats (avg/min/max per bug), success rate,
    retry statistics, and step-level performance breakdown.
    """
    async with get_session_ctx() as session:
        repo = BatchJobRepository(session)
        metrics = await repo.get_job_metrics(job_id)

    if metrics is None:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")

    return metrics


@router.get("/metrics/global")
async def get_global_metrics():
    """Get aggregated metrics across all completed batch jobs.

    Returns total job/bug counts, overall success rate,
    average timing, and most-failed steps ranking.
    """
    async with get_session_ctx() as session:
        repo = BatchJobRepository(session)
        metrics = await repo.get_global_metrics()

    return metrics


# --- Jira Integration Endpoints ---

jira_router = APIRouter(prefix="/api/v2/jira", tags=["jira"])


class JiraQueryRequest(BaseModel):
    """Request for POST /api/v2/jira/query."""
    jql: str = Field(..., description="JQL query string")
    jira_url: Optional[str] = Field(
        None,
        description="Jira instance URL (e.g., https://company.atlassian.net). "
        "Falls back to JIRA_URL env var if not provided.",
    )
    email: Optional[str] = Field(
        None,
        description="Jira user email. Falls back to JIRA_EMAIL env var if not provided.",
    )
    api_token: Optional[str] = Field(
        None,
        description="Jira API token. Falls back to JIRA_API_TOKEN env var if not provided.",
    )
    max_results: int = Field(
        default=50,
        ge=1,
        le=100,
        description="Maximum number of results to return (default 50, max 100)",
    )


class JiraBugInfo(BaseModel):
    """Bug information from Jira."""
    key: str
    summary: str
    status: str
    url: str
    priority: Optional[str] = None
    assignee: Optional[str] = None


class JiraQueryResponse(BaseModel):
    """Response for POST /api/v2/jira/query."""
    bugs: List[JiraBugInfo]
    total: int
    jql: str


class JiraErrorResponse(BaseModel):
    """Error response for Jira API failures."""
    error: str
    error_type: Literal["auth_failed", "jql_error", "connection_error", "unknown"]
    details: Optional[str] = None


@jira_router.post(
    "/query",
    response_model=JiraQueryResponse,
    responses={
        400: {"model": JiraErrorResponse, "description": "JQL syntax error"},
        401: {"model": JiraErrorResponse, "description": "Authentication failed"},
        502: {"model": JiraErrorResponse, "description": "Jira connection error"},
    },
)
async def query_jira_bugs(payload: JiraQueryRequest):
    """Query Jira for bugs using JQL.

    Credentials can be provided in the request body or via environment variables:
    - JIRA_URL: Jira instance URL
    - JIRA_EMAIL: User email
    - JIRA_API_TOKEN: API token

    Example JQL queries:
    - `project = MYPROJECT AND type = Bug`
    - `project = MYPROJECT AND type = Bug AND status = Open`
    - `assignee = currentUser() AND type = Bug`
    """
    import httpx
    import base64

    # Resolve credentials (request body > env vars)
    jira_url = payload.jira_url or os.environ.get("JIRA_URL")
    email = payload.email or os.environ.get("JIRA_EMAIL")
    api_token = payload.api_token or os.environ.get("JIRA_API_TOKEN")

    # Validate required credentials
    missing = []
    if not jira_url:
        missing.append("jira_url (or JIRA_URL env var)")
    if not email:
        missing.append("email (or JIRA_EMAIL env var)")
    if not api_token:
        missing.append("api_token (or JIRA_API_TOKEN env var)")

    if missing:
        raise HTTPException(
            status_code=400,
            detail={
                "error": f"Missing required credentials: {', '.join(missing)}",
                "error_type": "auth_failed",
            },
        )

    # Normalize Jira URL (remove trailing slash)
    jira_url = jira_url.rstrip("/")

    # Build auth header (Basic auth with email:token)
    auth_string = f"{email}:{api_token}"
    auth_bytes = base64.b64encode(auth_string.encode()).decode()

    # Build request to Jira REST API
    search_url = f"{jira_url}/rest/api/3/search"
    headers = {
        "Authorization": f"Basic {auth_bytes}",
        "Accept": "application/json",
    }
    params = {
        "jql": payload.jql,
        "maxResults": payload.max_results,
        "fields": "summary,status,priority,assignee",
    }

    logger.info(f"Jira query: JQL='{payload.jql}', maxResults={payload.max_results}")

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(search_url, headers=headers, params=params)

            if response.status_code == 401:
                raise HTTPException(
                    status_code=401,
                    detail={
                        "error": "Authentication failed. Check email and API token.",
                        "error_type": "auth_failed",
                    },
                )

            if response.status_code == 400:
                error_data = response.json()
                error_messages = error_data.get("errorMessages", [])
                raise HTTPException(
                    status_code=400,
                    detail={
                        "error": "Invalid JQL query",
                        "error_type": "jql_error",
                        "details": "; ".join(error_messages) if error_messages else str(error_data),
                    },
                )

            if response.status_code != 200:
                raise HTTPException(
                    status_code=502,
                    detail={
                        "error": f"Jira API returned status {response.status_code}",
                        "error_type": "unknown",
                        "details": response.text[:500],
                    },
                )

            data = response.json()

    except httpx.ConnectError as e:
        logger.error(f"Jira connection error: {e}")
        raise HTTPException(
            status_code=502,
            detail={
                "error": f"Failed to connect to Jira: {jira_url}",
                "error_type": "connection_error",
                "details": str(e),
            },
        )
    except httpx.TimeoutException:
        raise HTTPException(
            status_code=502,
            detail={
                "error": "Jira request timed out",
                "error_type": "connection_error",
            },
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Jira query error: {e}")
        raise HTTPException(
            status_code=500,
            detail={
                "error": "Unexpected error querying Jira",
                "error_type": "unknown",
                "details": str(e),
            },
        )

    # Parse response
    issues = data.get("issues", [])
    total = data.get("total", len(issues))

    bugs: List[JiraBugInfo] = []
    for issue in issues:
        key = issue.get("key", "")
        fields = issue.get("fields", {})

        status_obj = fields.get("status", {})
        status = status_obj.get("name", "Unknown") if status_obj else "Unknown"

        priority_obj = fields.get("priority")
        priority = priority_obj.get("name") if priority_obj else None

        assignee_obj = fields.get("assignee")
        assignee = assignee_obj.get("displayName") if assignee_obj else None

        issue_url = f"{jira_url}/browse/{key}"

        bugs.append(JiraBugInfo(
            key=key,
            summary=fields.get("summary", ""),
            status=status,
            url=issue_url,
            priority=priority,
            assignee=assignee,
        ))

    logger.info(f"Jira query returned {len(bugs)} bugs (total: {total})")

    return JiraQueryResponse(
        bugs=bugs,
        total=total,
        jql=payload.jql,
    )
