"""Batch Bug Fix API endpoints.

Provides endpoints for dispatching batch bug fix tasks, monitoring progress,
and controlling jobs (cancel/retry/delete).
Workflow execution is delegated to Temporal Worker (separate process).
SSE events arrive via the shared /api/internal/events/{run_id} endpoint.
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse, StreamingResponse

# Database imports
from app.database import get_session_ctx
from app.repositories.batch_job import BatchJobRepository
from app.models.db import BatchJobModel

# SSE infrastructure (unified EventBus)
from app.event_bus import push_event as push_node_event, subscribe_events

# Temporal client (lazy import to avoid startup dependency)
from app.temporal_adapter import get_client
from workflow.config import TASK_QUEUE

# Schemas (extracted to batch_schemas.py)
from .batch_schemas import (
    BatchBugFixConfig,
    BatchBugFixRequest,
    BatchBugFixResponse,
    BatchDeleteRequest,
    BatchDeleteResponse,
    BatchJobListResponse,
    BatchJobStatusResponse,
    BatchJobSummary,
    BugStatus,
    DryRunBugPreview,
    DryRunResponse,
    JobControlResponse,
)

logger = logging.getLogger("workflow.routes.batch")

router = APIRouter(prefix="/api/v2/batch", tags=["batch"])

# No in-memory workflow handles — use Temporal client to get handles by ID.
# This survives FastAPI restarts (workflow ID = "batch-{job_id}").


# --- Helpers ---


def _extract_jira_key_from_url(url: str) -> str:
    """Extract Jira issue key from URL (e.g. XSZS-15463)."""
    match = re.search(r"([A-Z][A-Z0-9]+-\d+)", url)
    return match.group(1) if match else url.rsplit("/", 1)[-1]


# Canonical visible pipeline steps (matches NODE_TO_STEP in batch_activities)
_DRY_RUN_STEPS = [
    "获取 Bug 信息",
    "修复 Bug",
    "验证修复结果",
    "修复完成 / 修复失败",
]


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


# --- Batch Bug Fix CRUD Endpoints ---


@router.post("/bug-fix", status_code=201)
async def create_batch_bug_fix(payload: BatchBugFixRequest):
    """Start a batch bug fix job, or return a dry-run preview.

    If dry_run=true, returns a preview of what would happen without
    creating a DB record or starting a Temporal workflow.
    Otherwise dispatches bug fix tasks to Temporal Worker.

    If workspace_id is provided, inherits config_defaults from the workspace
    (job-level config overrides workspace defaults).
    """
    cwd = payload.cwd or "."
    config = payload.config or BatchBugFixConfig()

    # --- Resolve workspace config inheritance ---
    workspace_id = payload.workspace_id
    if workspace_id:
        from app.repositories.workspace import WorkspaceRepository
        async with get_session_ctx() as session:
            ws_repo = WorkspaceRepository(session)
            ws = await ws_repo.get(workspace_id)
        if not ws:
            raise HTTPException(status_code=404, detail=f"Workspace '{workspace_id}' not found")
        # Inherit cwd from workspace repo_path if not explicitly provided
        if not payload.cwd:
            cwd = ws.repo_path
        # Merge config: workspace defaults ← job overrides
        if ws.config_defaults:
            merged = {**ws.config_defaults}
            merged.update(config.model_dump())
            config = BatchBugFixConfig(**{
                k: v for k, v in merged.items()
                if k in BatchBugFixConfig.model_fields
            })

    # --- Dry-run mode: preview only, no side effects ---
    if payload.dry_run:
        bugs_preview = [
            DryRunBugPreview(
                url=url.strip(),
                jira_key=_extract_jira_key_from_url(url.strip()),
                expected_steps=_DRY_RUN_STEPS,
            )
            for url in payload.jira_urls
        ]
        return JSONResponse(
            status_code=200,
            content=DryRunResponse(
                total_bugs=len(bugs_preview),
                cwd=cwd,
                config=config,
                bugs=bugs_preview,
                expected_steps_per_bug=_DRY_RUN_STEPS,
            ).model_dump(),
        )

    # --- Normal mode: create job + start workflow ---
    job_id = f"job_{uuid.uuid4().hex[:12]}"
    now = datetime.now(timezone.utc).isoformat()

    # Save to database (include cwd in config for retry support)
    config_to_store = config.model_dump()
    config_to_store["cwd"] = cwd

    async with get_session_ctx() as session:
        repo = BatchJobRepository(session)
        await repo.create(
            job_id=job_id,
            target_group_id="",
            jira_urls=payload.jira_urls,
            fixer_peer_id="",
            verifier_peer_id="",
            config=config_to_store,
            workspace_id=workspace_id,
        )
        # Touch workspace last_used_at
        if workspace_id:
            from app.repositories.workspace import WorkspaceRepository
            ws_repo = WorkspaceRepository(session)
            await ws_repo.touch(workspace_id)
        logger.info(f"Job {job_id}: Saved to database (workspace={workspace_id})")

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
        except Exception as db_err:
            logger.error(
                f"Job {job_id}: Failed to mark orphan job as failed in DB: {db_err}"
            )
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
    workspace_id: Optional[str] = Query(None, description="Filter by workspace ID"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page"),
):
    """List batch bug fix jobs with pagination."""
    async with get_session_ctx() as session:
        repo = BatchJobRepository(session)
        jobs, total = await repo.list(
            status=status,
            workspace_id=workspace_id,
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

    # Stream events from EventBus (events arrive from Temporal Worker
    # via HTTP POST to /api/internal/events/{job_id}).
    # subscribe_events stops automatically on job_done / workflow_complete.
    async for event_str in subscribe_events(job_id):
        yield event_str


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


@router.post("/bug-fix/{job_id}/retry/{bug_index}", response_model=JobControlResponse)
async def retry_single_bug(job_id: str, bug_index: int):
    """Retry a single failed bug in a batch job.

    Resets the bug's status to pending, starts a new Temporal workflow
    for just this one bug, and returns control response.
    """
    # 1. Validate job exists
    async with get_session_ctx() as session:
        repo = BatchJobRepository(session)
        db_job = await repo.get(job_id)

    if not db_job:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")

    # 2. Validate bug exists
    target_bug = None
    for b in db_job.bugs:
        if b.bug_index == bug_index:
            target_bug = b
            break

    if not target_bug:
        raise HTTPException(
            status_code=404,
            detail=f"Bug at index {bug_index} not found in job '{job_id}'",
        )

    # 3. Validate bug is in a retryable state
    if target_bug.status not in ("failed", "skipped"):
        raise HTTPException(
            status_code=400,
            detail=f"Bug at index {bug_index} has status '{target_bug.status}', "
            f"can only retry failed/skipped bugs",
        )

    # 4. Reset bug status in DB
    async with get_session_ctx() as session:
        repo = BatchJobRepository(session)
        bug = await repo.get_bug(job_id, bug_index)
        if bug:
            bug.status = "pending"
            bug.error = None
            bug.started_at = None
            bug.completed_at = None
            bug.steps = None
            await session.flush()
        await repo.update_status(job_id, "running")

    # 5. Recover config and cwd from stored job config
    stored_config = db_job.config or {}
    cwd = stored_config.get("cwd", ".")
    # Remaining keys are the workflow config (validation_level, etc.)
    workflow_config = {
        k: v for k, v in stored_config.items()
        if k in ("validation_level", "failure_policy", "max_retries")
    }

    # 6. Start new Temporal workflow for this single bug
    retry_workflow_id = f"batch-{job_id}-retry-{bug_index}-{uuid.uuid4().hex[:8]}"
    workflow_params = {
        "job_id": job_id,
        "jira_urls": [target_bug.url],
        "cwd": cwd,
        "config": workflow_config,
        "bug_index_offset": bug_index,
    }

    try:
        client = await get_client()
        await client.start_workflow(
            "BatchBugFixWorkflow",
            workflow_params,
            id=retry_workflow_id,
            task_queue=TASK_QUEUE,
        )
        logger.info(
            f"Job {job_id}: Retry workflow started for bug {bug_index} "
            f"(workflow_id={retry_workflow_id})"
        )
    except Exception as e:
        logger.error(f"Job {job_id}: Failed to start retry workflow: {e}")
        # Revert status on failure
        try:
            async with get_session_ctx() as session:
                repo = BatchJobRepository(session)
                await repo.update_bug_status(job_id, bug_index, "failed", error=str(e))
        except Exception as db_err:
            logger.error(
                f"Job {job_id}: Failed to revert bug {bug_index} status after retry failure: {db_err}"
            )
        raise HTTPException(
            status_code=503,
            detail=f"Failed to start retry workflow: {e}. Is Temporal running?",
        )

    return JobControlResponse(
        success=True,
        job_id=job_id,
        status="running",
        message=f"Retry started for bug {bug_index}",
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
    except Exception as e:
        logger.debug(f"Job {job_id}: Temporal workflow cancel skipped (may already be done): {e}")

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


@router.post("/bug-fix/batch-delete", response_model=BatchDeleteResponse)
async def batch_delete_jobs(request: BatchDeleteRequest):
    """Delete multiple batch jobs at once."""
    deleted = []
    failed = []
    for job_id in request.job_ids:
        try:
            await delete_batch_job(job_id)
            deleted.append(job_id)
        except Exception as e:
            logger.warning(f"Batch delete: failed to delete job {job_id}: {e}")
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
