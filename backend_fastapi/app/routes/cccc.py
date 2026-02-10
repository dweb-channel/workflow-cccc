"""CCCC Integration API endpoints.

Provides endpoints for listing CCCC groups and dispatching batch bug fix tasks.
"""

from __future__ import annotations

import asyncio
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Literal, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from workflow.agents.cccc import list_all_groups, send_cross_group_message
from workflow.engine.graph_builder import (
    EdgeDefinition,
    NodeConfig,
    WorkflowDefinition,
)
from workflow.engine.executor import execute_dynamic_workflow

# Import template utilities
from app.templates import load_template, template_to_workflow_definition

# Database imports
from app.database import get_session, get_session_ctx
from app.batch_job_repository import BatchJobRepository
from app.db_models import BatchJobModel, BugResultModel

logger = logging.getLogger("workflow.routes.cccc")

router = APIRouter(prefix="/api/v2/cccc", tags=["cccc"])

# In-memory cache for active jobs (used during workflow execution for SSE sync)
# Jobs are persisted to DB, this is just for real-time tracking
BATCH_JOBS_CACHE: Dict[str, Dict[str, Any]] = {}

# Active workflow tasks (for cancellation if needed)
WORKFLOW_TASKS: Dict[str, asyncio.Task] = {}

# SSE streams for real-time progress updates
JOB_SSE_QUEUES: Dict[str, asyncio.Queue] = {}

# --- Concurrency locks for global state ---
_cache_lock = asyncio.Lock()
_tasks_lock = asyncio.Lock()
_sse_lock = asyncio.Lock()
_steps_lock = asyncio.Lock()

# Maximum execution time for a batch workflow (seconds)
WORKFLOW_TIMEOUT = int(os.environ.get("WORKFLOW_TIMEOUT", "3600"))  # 1 hour default

# Node ID → user-facing step mapping (None = internal node, not exposed to UI)
NODE_TO_STEP: Dict[str, Optional[tuple]] = {
    "get_current_bug": ("fetching", "获取 Bug 信息"),
    "fix_bug_peer": ("fixing", "修复 Bug"),
    "verify_fix": ("verifying", "验证修复结果"),
    "check_verify_result": None,  # internal
    "check_retry": None,  # internal
    "increment_retry": ("retrying", "准备重试"),
    "update_success": ("completed", "修复完成"),
    "update_failure": ("failed", "修复失败"),
    "check_more_bugs": None,  # internal
    "input_node": None,  # internal
    "output_node": None,  # internal
}

# Track per-bug execution steps during workflow execution
# Key: job_id, Value: Dict[bug_index, List[step_dict]]
JOB_BUG_STEPS: Dict[str, Dict[int, List[Dict[str, Any]]]] = {}


# --- Schemas ---


class EnabledPeer(BaseModel):
    """Enabled peer summary."""
    id: str
    title: str
    role: str
    enabled: bool = True
    running: bool = False


class CCCCGroupResponse(BaseModel):
    """CCCC Group information for the API response."""
    group_id: str
    title: str
    state: str
    running: bool
    ready: bool
    enabled_peers: int
    peers: List[EnabledPeer]
    scope: Optional[str] = None


class CCCCGroupsListResponse(BaseModel):
    """Response for GET /api/v2/cccc/groups."""
    groups: List[CCCCGroupResponse]
    total: int


# --- Helper functions ---


def _determine_actor_role(actors: List[dict], actor_id: str) -> str:
    """Determine actor role based on position (first enabled = foreman, rest = peer)."""
    enabled_actors = [a for a in actors if a.get("enabled")]
    if not enabled_actors:
        return "peer"
    if enabled_actors[0].get("id") == actor_id:
        return "foreman"
    return "peer"


# --- Endpoints ---


@router.get("/groups", response_model=CCCCGroupsListResponse)
async def list_cccc_groups(
    filter: Optional[str] = Query(
        None,
        description="Filter groups: 'running' (only running), 'ready' (only ready for tasks)",
    ),
):
    """List all local CCCC working groups.

    Returns groups with their status and peer availability.
    Use filter=running to get only running groups.
    Use filter=ready to get only groups that are ready to accept tasks.
    """
    # Read groups from filesystem
    groups_resp = list_all_groups()

    if not groups_resp.get("ok"):
        error = groups_resp.get("error", {})
        error_msg = error.get("message", "Failed to list CCCC groups")
        error_code = error.get("code", "daemon_error")

        if error_code == "connection_refused":
            raise HTTPException(status_code=503, detail="CCCC daemon is not running")
        raise HTTPException(status_code=500, detail=error_msg)

    raw_groups = groups_resp.get("result", {}).get("groups", [])

    # Process each group to add ready status and peer info
    result_groups: List[CCCCGroupResponse] = []

    for g in raw_groups:
        group_id = g.get("group_id", "")
        running = g.get("running", False)
        state = g.get("state", "unknown")
        title = g.get("title", group_id)

        # Get scope from first scope if available
        scopes = g.get("scopes", [])
        scope = scopes[0].get("label") if scopes else None

        # Get actors from group data (already loaded from yaml)
        actors = g.get("actors", [])
        enabled_peers: List[EnabledPeer] = []

        for actor in actors:
            if not actor.get("enabled"):
                continue
            # Determine role based on position
            role = _determine_actor_role(actors, actor.get("id", ""))
            # Actor is running if group is running and actor has a running session
            actor_running = running and actor.get("running", True)
            if role == "peer":
                enabled_peers.append(EnabledPeer(
                    id=actor.get("id", ""),
                    title=actor.get("title", ""),
                    role=role,
                    enabled=True,
                    running=actor_running,
                ))

        # Group is ready if it's running and has at least one enabled peer
        ready = running and len(enabled_peers) > 0

        group_response = CCCCGroupResponse(
            group_id=group_id,
            title=title,
            state=state,
            running=running,
            ready=ready,
            enabled_peers=len(enabled_peers),
            peers=enabled_peers,
            scope=scope,
        )

        # Apply filter
        if filter == "running" and not running:
            continue
        if filter == "ready" and not ready:
            continue

        result_groups.append(group_response)

    return CCCCGroupsListResponse(
        groups=result_groups,
        total=len(result_groups),
    )


# --- Batch Bug Fix Schemas ---


class BatchBugFixConfig(BaseModel):
    """Configuration for batch bug fix job."""
    validation_level: Literal["minimal", "standard", "thorough"] = "standard"
    failure_policy: Literal["stop", "skip", "retry"] = "skip"
    max_retries: int = Field(default=3, ge=1, le=10)


class BatchBugFixRequest(BaseModel):
    """Request for POST /api/v2/batch-bug-fix."""
    target_group_id: str = Field(..., description="Target CCCC Group ID")
    jira_urls: List[str] = Field(..., min_length=1, description="List of Jira bug URLs")
    fixer_peer_id: Optional[str] = Field(
        None,
        description="Peer ID to execute bug fixes. If not specified, uses first available peer."
    )
    verifier_peer_id: Optional[str] = Field(
        None,
        description="Peer ID to verify bug fixes. If not specified, uses same peer as fixer."
    )
    config: Optional[BatchBugFixConfig] = None


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
    """Response for POST /api/v2/batch-bug-fix."""
    job_id: str
    status: Literal["started", "running", "completed", "failed", "cancelled"]
    total_bugs: int
    target_group_id: str
    created_at: str


class BatchJobStatusResponse(BaseModel):
    """Response for GET /api/v2/batch-bug-fix/{job_id}."""
    job_id: str
    status: Literal["started", "running", "completed", "failed", "cancelled"]
    total_bugs: int
    completed: int
    failed: int
    skipped: int
    in_progress: int
    pending: int
    target_group_id: str
    bugs: List[BugStatus]
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class BatchJobSummary(BaseModel):
    """Summary of a batch job for list view."""
    job_id: str
    status: Literal["started", "running", "completed", "failed", "cancelled"]
    target_group_id: str
    total_bugs: int
    completed: int
    failed: int
    created_at: str
    updated_at: str


class BatchJobListResponse(BaseModel):
    """Response for GET /api/v2/batch-bug-fix (list)."""
    jobs: List[BatchJobSummary]
    total: int
    page: int
    page_size: int


# --- Workflow Execution ---


async def execute_batch_bug_fix_workflow(
    job_id: str,
    jira_urls: List[str],
    target_group_id: str,
    fixer_peer_id: str,
    verifier_peer_id: str,
    config: Dict[str, Any],
) -> None:
    """Execute the batch bug fix workflow asynchronously.

    This function:
    1. Loads the bug_fix_batch template
    2. Executes the workflow with initial state
    3. Syncs progress back to BATCH_JOBS_CACHE during execution (real-time via SSE hook)
    4. Final sync when workflow completes

    Args:
        job_id: Unique job identifier
        jira_urls: List of Jira bug URLs to fix
        target_group_id: Target CCCC group ID
        fixer_peer_id: Peer ID to execute bug fixes
        verifier_peer_id: Peer ID to verify bug fixes
        config: Job configuration (validation_level, failure_policy, max_retries)
    """
    logger.info(f"Starting workflow execution for job {job_id}")

    async with _cache_lock:
        if job_id not in BATCH_JOBS_CACHE:
            logger.error(f"Job {job_id} not found in BATCH_JOBS_CACHE")
            return
        job = BATCH_JOBS_CACHE[job_id]
        job["status"] = "running"
        now = datetime.now(timezone.utc).isoformat()
        job["updated_at"] = now

        # Mark first bug as in_progress and push SSE event
        if job["bugs"]:
            first_bug = job["bugs"][0]
            first_bug["status"] = "in_progress"
            first_bug["started_at"] = now

    if job.get("bugs"):
        push_job_event(job_id, "bug_started", {
            "bug_index": 0,
            "url": job["bugs"][0].get("url", ""),
            "timestamp": now,
        })

    # Track last synced results count for incremental sync
    last_results_count = 0

    try:
        # Load workflow template
        template = load_template("bug_fix_batch")
        wf_dict = template_to_workflow_definition(template)

        # Create WorkflowDefinition
        nodes = [NodeConfig(**n) for n in wf_dict["nodes"]]
        edges = [EdgeDefinition(**e) for e in wf_dict["edges"]]

        workflow_def = WorkflowDefinition(
            name=wf_dict["name"],
            nodes=nodes,
            edges=edges,
            entry_point=wf_dict.get("entry_point"),
            max_iterations=wf_dict.get("max_iterations", 100),
        )

        # Prepare initial state
        initial_state = {
            "bugs": jira_urls,
            "bugs_count": len(jira_urls),
            "job_id": job_id,
            "target_group_id": target_group_id,
            "fixer_peer_id": fixer_peer_id,
            "verifier_peer_id": verifier_peer_id,
            "current_index": 0,
            "retry_count": 0,
            "results": [],
            "config": config,
        }

        logger.info(
            f"Job {job_id}: Executing workflow with {len(jira_urls)} bugs, "
            f"max_iterations={workflow_def.max_iterations}"
        )

        # Execute workflow with real-time state sync
        final_state = await _execute_with_realtime_sync(
            workflow_def=workflow_def,
            initial_state=initial_state,
            job_id=job_id,
        )

        # Final sync to ensure all results are captured
        await _sync_workflow_results_to_job(job_id, final_state)

        logger.info(f"Job {job_id}: Workflow execution completed")

    except asyncio.CancelledError:
        # Let the timeout wrapper (_run_workflow_with_timeout) handle this
        logger.info(f"Job {job_id}: Workflow cancelled")
        async with _cache_lock:
            job["status"] = "cancelled"
            job["updated_at"] = datetime.now(timezone.utc).isoformat()
        raise  # Re-raise so wrapper can distinguish timeout vs user cancel

    except Exception as e:
        logger.error(f"Job {job_id}: Workflow execution failed: {e}")
        async with _cache_lock:
            job["status"] = "failed"
            job["error"] = str(e)
            job["updated_at"] = datetime.now(timezone.utc).isoformat()
        push_job_event(job_id, "job_done", {
            "status": "failed",
            "error": str(e),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })


async def _execute_with_realtime_sync(
    workflow_def: WorkflowDefinition,
    initial_state: Dict[str, Any],
    job_id: str,
) -> Dict[str, Any]:
    """Execute workflow with real-time state synchronization.

    This wraps execute_dynamic_workflow and adds hooks to sync
    state to BATCH_JOBS_CACHE after each update_state node completes.
    Also pushes step-level SSE events for each user-visible node.

    Args:
        workflow_def: The workflow definition
        initial_state: Initial workflow state
        job_id: Job ID for state sync

    Returns:
        Final workflow state
    """
    from workflow.engine.graph_builder import build_graph_from_config, detect_loops
    from workflow.sse import push_sse_event

    logger.info(f"Job {job_id}: Starting workflow with real-time sync")

    state = {**initial_state, "run_id": job_id}
    last_synced_index = -1

    # Initialize step tracking for this job (lock not needed: single writer at init)
    JOB_BUG_STEPS[job_id] = {}

    # Track node start times for duration calculation
    node_start_times: Dict[str, datetime] = {}

    # Build and compile the graph
    compiled_graph = build_graph_from_config(workflow_def)

    # Detect loops for iteration control
    loops = detect_loops(workflow_def)
    has_loops = len(loops) > 0

    # Calculate recursion limit
    recursion_limit = workflow_def.max_iterations * len(workflow_def.nodes) + len(workflow_def.nodes)
    config = {"recursion_limit": recursion_limit} if has_loops else {}

    # Execute with streaming to capture each node completion
    async for event in compiled_graph.astream(state, config=config):
        for node_id, node_output in event.items():
            # With our state preservation fix, node_output contains the full state
            # Update our tracking state with the latest values
            if isinstance(node_output, dict):
                # Merge all fields from node output into tracking state
                for key, value in node_output.items():
                    state[key] = value

            # --- Step-level SSE events ---
            bug_index = state.get("current_index", 0)
            # After update_success/update_failure, current_index has been incremented,
            # so the bug that just completed is at index - 1
            if node_id in ["update_success", "update_failure", "check_more_bugs"]:
                bug_index = max(0, bug_index - 1)

            step_info = NODE_TO_STEP.get(node_id)
            now = datetime.now(timezone.utc)
            now_iso = now.isoformat()

            if step_info is not None:
                step_name, step_label = step_info
                attempt = state.get("retry_count", 0) + 1 if step_name in ("fixing", "verifying", "retrying") else None

                # Calculate duration if we have a start time
                duration_ms = None
                start_key = f"{bug_index}:{node_id}"
                if start_key in node_start_times:
                    duration_ms = (now - node_start_times[start_key]).total_seconds() * 1000

                # Extract output preview from node output
                output_preview = None
                if isinstance(node_output, dict):
                    # CCCCPeerNode returns {response, success, peer_id}
                    if "response" in node_output:
                        resp = node_output["response"]
                        if isinstance(resp, str) and len(resp) > 0:
                            output_preview = resp[:200] + ("..." if len(resp) > 200 else "")
                    # VerifyNode returns {verified, message, details}
                    elif "message" in node_output:
                        msg = node_output["message"]
                        if isinstance(msg, str) and len(msg) > 0:
                            output_preview = msg[:200] + ("..." if len(msg) > 200 else "")

                # Determine step status
                step_status = "completed"
                step_error = None
                if step_name == "failed":
                    step_status = "failed"
                elif isinstance(node_output, dict):
                    if node_output.get("success") is False:
                        step_status = "failed"
                        step_error = output_preview
                    elif node_output.get("verified") is False:
                        step_status = "failed"
                        step_error = output_preview

                # Build step record
                step_record = {
                    "step": node_id,
                    "label": step_label,
                    "status": step_status,
                    "started_at": node_start_times.get(start_key, now).isoformat(),
                    "completed_at": now_iso,
                    "duration_ms": round(duration_ms, 1) if duration_ms else None,
                    "output_preview": output_preview,
                    "error": step_error,
                }
                if attempt is not None:
                    step_record["attempt"] = attempt

                # Store step in tracking dict (safe append)
                job_steps = JOB_BUG_STEPS.setdefault(job_id, {})
                job_steps.setdefault(bug_index, []).append(step_record)

                # Push bug_step_completed SSE event
                push_job_event(job_id, "bug_step_completed", {
                    "bug_index": bug_index,
                    "step": node_id,
                    "label": step_label,
                    "status": step_status,
                    "duration_ms": round(duration_ms, 1) if duration_ms else None,
                    "output_preview": output_preview,
                    "error": step_error,
                    "attempt": attempt,
                    "timestamp": now_iso,
                })

            # --- Push bug_step_started for the NEXT user-visible node ---
            # LangGraph astream yields node completion in order, so after node A completes,
            # the next node in the graph will start. We can infer the next step from the
            # workflow edges, but a simpler approach: push started event when we first see
            # a user-visible node (record its start time).
            # We record the start time for each node when we DON'T yet have one.
            # The next iteration's step_info check will calculate duration from this.
            _record_next_step_start(job_id, node_id, bug_index, state, node_start_times)

            # Check if this is an update_state node (results may have changed)
            if "results" in node_output or node_id in ["update_success", "update_failure"]:
                # Get current results from state (now at top level)
                current_results = state.get("results", [])
                if not isinstance(current_results, list):
                    # Try to get from nested node output
                    nested = node_output.get(node_id, {})
                    if isinstance(nested, dict):
                        current_results = nested.get("results", [])

                # Sync incrementally if new results
                if isinstance(current_results, list) and len(current_results) > last_synced_index + 1:
                    await _sync_incremental_results(job_id, current_results, last_synced_index + 1)
                    last_synced_index = len(current_results) - 1
                    logger.info(
                        f"Job {job_id}: Synced result {last_synced_index + 1}/{state.get('bugs_count', '?')}"
                    )

                    # Persist steps to database for completed bugs
                    await _persist_bug_steps(job_id, last_synced_index)

    # Clean up step tracking
    JOB_BUG_STEPS.pop(job_id, None)

    state["success"] = True
    return state


def _record_next_step_start(
    job_id: str,
    completed_node_id: str,
    bug_index: int,
    state: Dict[str, Any],
    node_start_times: Dict[str, datetime],
) -> None:
    """After a node completes, predict and record the start of the next user-visible node.

    Uses workflow edge knowledge to determine the likely next node and push
    a bug_step_started SSE event.
    """
    # Map from completed node to likely next user-visible node
    next_node_map: Dict[str, Optional[str]] = {
        "get_current_bug": "fix_bug_peer",
        "fix_bug_peer": "verify_fix",
        "verify_fix": None,  # depends on condition result
        "increment_retry": "fix_bug_peer",
        "input_node": "get_current_bug",
    }

    next_node = next_node_map.get(completed_node_id)
    if next_node is None:
        return

    next_step_info = NODE_TO_STEP.get(next_node)
    if next_step_info is None:
        return

    now = datetime.now(timezone.utc)
    start_key = f"{bug_index}:{next_node}"
    node_start_times[start_key] = now

    step_name, step_label = next_step_info
    attempt = state.get("retry_count", 0) + 1 if step_name in ("fixing", "verifying") else None

    event_data: Dict[str, Any] = {
        "bug_index": bug_index,
        "step": next_node,
        "label": step_label,
        "timestamp": now.isoformat(),
    }
    if attempt is not None:
        event_data["attempt"] = attempt

    push_job_event(job_id, "bug_step_started", event_data)


async def _persist_bug_steps(job_id: str, bug_index: int) -> None:
    """Persist accumulated steps for a completed bug to the database."""
    steps = JOB_BUG_STEPS.get(job_id, {}).get(bug_index)
    if not steps:
        return

    try:
        async with get_session_ctx() as session:
            repo = BatchJobRepository(session)
            await repo.update_bug_steps(
                job_id=job_id,
                bug_index=bug_index,
                steps=steps,
            )
        logger.info(f"Job {job_id}: Persisted {len(steps)} steps for bug {bug_index}")
    except Exception as e:
        logger.error(f"Job {job_id}: Failed to persist steps for bug {bug_index}: {e}")
        push_job_event(job_id, "db_warning", {
            "message": f"Failed to persist steps for bug {bug_index}: {e}",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })


async def _sync_incremental_results(
    job_id: str,
    results: List[Dict[str, Any]],
    start_index: int,
) -> None:
    """Sync new results incrementally to cache, database, and push SSE events.

    Only syncs results from start_index onwards.

    Args:
        job_id: Job identifier
        results: Full results array
        start_index: Index to start syncing from
    """
    if job_id not in BATCH_JOBS_CACHE:
        return

    job = BATCH_JOBS_CACHE[job_id]
    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()

    # Track updates for DB sync
    db_updates: List[Dict[str, Any]] = []

    for i in range(start_index, len(results)):
        if i >= len(job["bugs"]):
            break

        result = results[i]
        bug = job["bugs"][i]

        result_status = result.get("status", "failed")
        error_msg = None

        if result_status == "completed":
            bug["status"] = "completed"
            # Push SSE event: bug_completed
            push_job_event(job_id, "bug_completed", {
                "bug_index": i,
                "url": bug.get("url", ""),
                "timestamp": now_iso,
            })
        elif result_status == "failed":
            bug["status"] = "failed"
            error_msg = result.get("error", result.get("response", "Unknown error"))
            bug["error"] = error_msg
            # Push SSE event: bug_failed
            push_job_event(job_id, "bug_failed", {
                "bug_index": i,
                "url": bug.get("url", ""),
                "error": bug["error"],
                "timestamp": now_iso,
            })
        elif result_status == "skipped":
            bug["status"] = "skipped"
            error_msg = result.get("error", "Skipped")
            bug["error"] = error_msg
            # Push SSE event: bug_failed (skipped is a type of failure)
            push_job_event(job_id, "bug_failed", {
                "bug_index": i,
                "url": bug.get("url", ""),
                "error": bug["error"],
                "skipped": True,
                "timestamp": now_iso,
            })

        bug["completed_at"] = now_iso
        db_updates.append({
            "bug_index": i,
            "status": bug["status"],
            "error": error_msg,
            "completed_at": now,
        })

    # Update job status in cache
    job["updated_at"] = now_iso

    # Mark in-progress bug if there's a next one
    next_bug_index = None
    bugs = job["bugs"]
    for i, bug in enumerate(bugs):
        if bug["status"] == "pending" and not bug.get("started_at"):
            bug["status"] = "in_progress"
            bug["started_at"] = now_iso
            next_bug_index = i
            # Push SSE event: bug_started
            push_job_event(job_id, "bug_started", {
                "bug_index": i,
                "url": bug.get("url", ""),
                "timestamp": now_iso,
            })
            break

    # Sync to database (errors pushed to SSE instead of silently swallowed)
    try:
        async with get_session_ctx() as session:
            repo = BatchJobRepository(session)
            for upd in db_updates:
                await repo.update_bug_status(
                    job_id=job_id,
                    bug_index=upd["bug_index"],
                    status=upd["status"],
                    error=upd.get("error"),
                    completed_at=upd.get("completed_at"),
                )
            if next_bug_index is not None:
                await repo.update_bug_status(
                    job_id=job_id,
                    bug_index=next_bug_index,
                    status="in_progress",
                    started_at=now,
                )
    except Exception as e:
        logger.error(f"Job {job_id}: Failed to sync to database: {e}")
        push_job_event(job_id, "db_warning", {
            "message": f"Database sync failed: {e}",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })


async def _sync_workflow_results_to_job(job_id: str, final_state: Dict[str, Any]) -> None:
    """Sync workflow execution results back to cache and database.

    Updates the job's bug statuses based on workflow results array.

    Args:
        job_id: Job identifier
        final_state: Final workflow state containing results array
    """
    if job_id not in BATCH_JOBS_CACHE:
        logger.warning(f"Job {job_id} not found for result sync")
        return

    job = BATCH_JOBS_CACHE[job_id]
    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()

    # Get results from workflow state
    results = final_state.get("results", [])
    workflow_success = final_state.get("success", False)

    # Update each bug status based on results
    for i, result in enumerate(results):
        if i < len(job["bugs"]):
            bug = job["bugs"][i]
            result_status = result.get("status", "failed")

            # Map workflow status to job status
            if result_status == "completed":
                bug["status"] = "completed"
            elif result_status == "failed":
                bug["status"] = "failed"
                bug["error"] = result.get("error", result.get("response", "Unknown error"))
            elif result_status == "skipped":
                bug["status"] = "skipped"
                bug["error"] = result.get("error", "Skipped due to failure policy")

            bug["completed_at"] = now_iso

    # Calculate overall job status
    bugs = job["bugs"]
    completed = sum(1 for b in bugs if b["status"] == "completed")
    failed = sum(1 for b in bugs if b["status"] == "failed")
    skipped = sum(1 for b in bugs if b["status"] == "skipped")
    pending = sum(1 for b in bugs if b["status"] == "pending")

    if pending == 0:
        # All bugs processed
        job["status"] = "completed" if failed == 0 else "failed"
    elif workflow_success:
        job["status"] = "completed"
    else:
        job["status"] = "failed"

    job["updated_at"] = now_iso
    logger.info(
        f"Job {job_id}: Synced results - "
        f"completed={completed}, failed={failed}, skipped={skipped}, pending={pending}"
    )

    # Sync final status to database
    try:
        async with get_session_ctx() as session:
            repo = BatchJobRepository(session)
            await repo.update_status(job_id, job["status"])
            # Update any remaining bug statuses
            for i, bug in enumerate(bugs):
                await repo.update_bug_status(
                    job_id=job_id,
                    bug_index=i,
                    status=bug["status"],
                    error=bug.get("error"),
                    completed_at=now if bug.get("completed_at") else None,
                )
        logger.info(f"Job {job_id}: Final results synced to database")
    except Exception as e:
        logger.error(f"Job {job_id}: Failed to sync final results to database: {e}")
        push_job_event(job_id, "db_warning", {
            "message": f"Final DB sync failed: {e}",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

    # Push SSE event: job_done
    push_job_event(job_id, "job_done", {
        "status": job["status"],
        "completed": completed,
        "failed": failed,
        "skipped": skipped,
        "total": len(bugs),
        "timestamp": now,
    })


# --- Workflow Timeout Wrapper ---


async def _run_workflow_with_timeout(
    job_id: str,
    jira_urls: List[str],
    target_group_id: str,
    fixer_peer_id: str,
    verifier_peer_id: str,
    config: Dict[str, Any],
) -> None:
    """Run execute_batch_bug_fix_workflow with a global timeout.

    The inner function handles its own exceptions (including CancelledError),
    so we use a deadline-based approach instead of asyncio.wait_for.
    """
    deadline = asyncio.get_event_loop().time() + WORKFLOW_TIMEOUT
    task = asyncio.current_task()

    # Schedule a callback to cancel this task at the deadline
    loop = asyncio.get_event_loop()
    timeout_handle = loop.call_at(deadline, task.cancel)

    try:
        await execute_batch_bug_fix_workflow(
            job_id=job_id,
            jira_urls=jira_urls,
            target_group_id=target_group_id,
            fixer_peer_id=fixer_peer_id,
            verifier_peer_id=verifier_peer_id,
            config=config,
        )
    except asyncio.CancelledError:
        # Check if this is a timeout or user-initiated cancel
        if loop.time() >= deadline - 1:  # Within 1s of deadline = timeout
            error_msg = f"Workflow timed out after {WORKFLOW_TIMEOUT}s"
            logger.error(f"Job {job_id}: {error_msg}")
            async with _cache_lock:
                if job_id in BATCH_JOBS_CACHE:
                    job = BATCH_JOBS_CACHE[job_id]
                    job["status"] = "failed"
                    job["error"] = error_msg
                    job["updated_at"] = datetime.now(timezone.utc).isoformat()
            push_job_event(job_id, "job_done", {
                "status": "failed",
                "error": error_msg,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
        else:
            # User-initiated cancel — re-raise to let outer cancel handling work
            raise
    finally:
        timeout_handle.cancel()  # Clean up the scheduled callback
        async with _tasks_lock:
            WORKFLOW_TASKS.pop(job_id, None)


# --- Batch Bug Fix Endpoints ---


@router.post("/batch-bug-fix", response_model=BatchBugFixResponse, status_code=201)
async def create_batch_bug_fix(payload: BatchBugFixRequest):
    """Start a batch bug fix job.

    Dispatches bug fix tasks to the specified CCCC group.
    Returns a job_id for tracking progress.
    """
    # Validate target group exists and is ready
    groups_resp = list_all_groups()
    if not groups_resp.get("ok"):
        raise HTTPException(status_code=500, detail="Failed to list CCCC groups")

    raw_groups = groups_resp.get("result", {}).get("groups", [])
    target_group = None
    for g in raw_groups:
        if g.get("group_id") == payload.target_group_id:
            target_group = g
            break

    if not target_group:
        raise HTTPException(
            status_code=400,
            detail=f"Target group '{payload.target_group_id}' not found"
        )

    if not target_group.get("running"):
        raise HTTPException(
            status_code=400,
            detail=f"Target group '{payload.target_group_id}' is not running"
        )

    # Check if group has enabled peers (exclude foreman - first enabled actor)
    actors = target_group.get("actors", [])
    first_enabled_id = None
    for a in actors:
        if a.get("enabled"):
            first_enabled_id = a.get("id")
            break
    enabled_peers = [
        a for a in actors
        if a.get("enabled") and a.get("id") != first_enabled_id
    ]
    if not enabled_peers:
        raise HTTPException(
            status_code=400,
            detail=f"Target group '{payload.target_group_id}' has no available peers"
        )

    # Determine fixer_peer_id and verifier_peer_id
    peer_ids = [p.get("id") for p in enabled_peers]
    default_peer_id = enabled_peers[0].get("id")

    fixer_peer_id = payload.fixer_peer_id
    if fixer_peer_id:
        # Validate specified fixer peer exists
        if fixer_peer_id not in peer_ids:
            raise HTTPException(
                status_code=400,
                detail=f"Fixer peer '{fixer_peer_id}' not found in group. Available peers: {peer_ids}"
            )
    else:
        # Default to first enabled peer
        fixer_peer_id = default_peer_id

    verifier_peer_id = payload.verifier_peer_id
    if verifier_peer_id:
        # Validate specified verifier peer exists
        if verifier_peer_id not in peer_ids:
            raise HTTPException(
                status_code=400,
                detail=f"Verifier peer '{verifier_peer_id}' not found in group. Available peers: {peer_ids}"
            )
    else:
        # Default to same as fixer peer
        verifier_peer_id = fixer_peer_id

    # Generate job ID
    job_id = f"job_{uuid.uuid4().hex[:12]}"
    now = datetime.now(timezone.utc).isoformat()

    # Create job record
    config = payload.config or BatchBugFixConfig()

    # Save to database
    async with get_session_ctx() as session:
        repo = BatchJobRepository(session)
        db_job = await repo.create(
            job_id=job_id,
            target_group_id=payload.target_group_id,
            jira_urls=payload.jira_urls,
            fixer_peer_id=fixer_peer_id,
            verifier_peer_id=verifier_peer_id,
            config=config.model_dump(),
        )
        logger.info(f"Job {job_id}: Saved to database")

    # Also populate in-memory cache for real-time tracking during workflow execution
    job = {
        "job_id": job_id,
        "status": "started",
        "target_group_id": payload.target_group_id,
        "config": config.model_dump(),
        "bugs": [
            {
                "url": url,
                "status": "pending",
                "error": None,
                "started_at": None,
                "completed_at": None,
                "steps": None,
                "retry_count": 0,
            }
            for url in payload.jira_urls
        ],
        "created_at": now,
        "updated_at": now,
    }
    async with _cache_lock:
        BATCH_JOBS_CACHE[job_id] = job

    # Start workflow execution asynchronously with timeout protection
    workflow_task = asyncio.create_task(
        _run_workflow_with_timeout(
            job_id=job_id,
            jira_urls=payload.jira_urls,
            target_group_id=payload.target_group_id,
            fixer_peer_id=fixer_peer_id,
            verifier_peer_id=verifier_peer_id,
            config=config.model_dump(),
        )
    )
    async with _tasks_lock:
        WORKFLOW_TASKS[job_id] = workflow_task

    logger.info(f"Job {job_id}: Workflow execution task started")

    # Optionally send notification message to target group
    source_group_id = os.environ.get("CCCC_GROUP_ID", "g_workflow_api")
    task_message = f"""[批量 Bug 修复任务已启动]

Job ID: {job_id}
Bug 数量: {len(payload.jira_urls)}
验证级别: {config.validation_level}
失败策略: {config.failure_policy}

工作流已自动启动，进度可通过 API 查询。"""

    # Send notification (best-effort, don't block on failure)
    try:
        send_cross_group_message(
            source_group_id=source_group_id,
            target_group_id=payload.target_group_id,
            text=task_message,
            sender_id="workflow-api",
            to=["@all"],
            priority="normal",
        )
    except Exception as e:
        logger.warning(f"Job {job_id}: Failed to send notification: {e}")

    return BatchBugFixResponse(
        job_id=job_id,
        status="started",
        total_bugs=len(payload.jira_urls),
        target_group_id=payload.target_group_id,
        created_at=now,
    )


def _db_job_to_dict(db_job: BatchJobModel) -> Dict[str, Any]:
    """Convert database job model to dict format for API responses."""
    return {
        "job_id": db_job.id,
        "status": db_job.status,
        "target_group_id": db_job.target_group_id,
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


@router.get("/batch-bug-fix/{job_id}", response_model=BatchJobStatusResponse)
async def get_batch_bug_fix_status(job_id: str):
    """Get the status of a batch bug fix job."""
    job = None

    # First check in-memory cache (for active jobs)
    async with _cache_lock:
        if job_id in BATCH_JOBS_CACHE:
            job = BATCH_JOBS_CACHE[job_id]
    if job is None:
        # Query from database
        async with get_session_ctx() as session:
            repo = BatchJobRepository(session)
            db_job = await repo.get(job_id)
            if db_job:
                job = _db_job_to_dict(db_job)

    if not job:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")

    bugs = job.get("bugs", [])

    # Enrich cache bugs with live step data from JOB_BUG_STEPS
    if job_id in JOB_BUG_STEPS:
        for i, bug in enumerate(bugs):
            live_steps = JOB_BUG_STEPS[job_id].get(i)
            if live_steps:
                bug["steps"] = live_steps
                bug["retry_count"] = _count_retries(live_steps)

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
        target_group_id=job.get("target_group_id", ""),
        bugs=[BugStatus(**b) for b in bugs],
        created_at=job.get("created_at", ""),
        updated_at=job.get("updated_at", ""),
    )


@router.get("/batch-bug-fix", response_model=BatchJobListResponse)
async def list_batch_bug_fix_jobs(
    status: Optional[str] = Query(None, description="Filter by job status"),
    target_group_id: Optional[str] = Query(None, description="Filter by target group"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page"),
):
    """List batch bug fix jobs with pagination.

    Returns job summaries with basic statistics.
    Use GET /batch-bug-fix/{job_id} for detailed bug-level status.
    """
    async with get_session_ctx() as session:
        repo = BatchJobRepository(session)
        jobs, total = await repo.list(
            status=status,
            target_group_id=target_group_id,
            page=page,
            page_size=page_size,
        )

        job_summaries = []
        for db_job in jobs:
            # Calculate stats
            stats = {s: 0 for s in ["completed", "failed", "skipped", "in_progress", "pending"]}
            for bug in db_job.bugs:
                if bug.status in stats:
                    stats[bug.status] += 1

            job_summaries.append(BatchJobSummary(
                job_id=db_job.id,
                status=db_job.status,
                target_group_id=db_job.target_group_id,
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


# --- Task Polling API for Target Groups ---


class TaskForGroup(BaseModel):
    """Task information for target group polling."""
    job_id: str
    bug_index: int
    url: str
    status: str
    config: BatchBugFixConfig


class TasksForGroupResponse(BaseModel):
    """Response for GET /api/v2/cccc/tasks."""
    tasks: List[TaskForGroup]
    total: int


class BugStatusUpdateRequest(BaseModel):
    """Request for updating bug status."""
    status: Literal["in_progress", "completed", "failed", "skipped"]
    error: Optional[str] = None


class BugStatusUpdateResponse(BaseModel):
    """Response for bug status update."""
    success: bool
    job_id: str
    bug_index: int
    new_status: str
    job_status: str


@router.get("/tasks", response_model=TasksForGroupResponse)
async def get_tasks_for_group(
    group_id: str = Query(..., description="Target group ID to get tasks for"),
    status: Optional[str] = Query(
        None,
        description="Filter by bug status: 'pending', 'in_progress', 'all' (default: pending)",
    ),
):
    """Get tasks assigned to a specific group.

    Target groups should poll this endpoint to get tasks assigned to them.
    Returns pending tasks by default.
    """
    filter_status = status or "pending"
    tasks: List[TaskForGroup] = []

    # Snapshot cache keys under lock to avoid RuntimeError during iteration
    async with _cache_lock:
        cache_snapshot = list(BATCH_JOBS_CACHE.items())

    for job_id, job in cache_snapshot:
        # Only return tasks for the specified group
        if job.get("target_group_id") != group_id:
            continue

        config = BatchBugFixConfig(**job.get("config", {}))

        for idx, bug in enumerate(job.get("bugs", [])):
            bug_status = bug.get("status", "pending")

            # Apply status filter
            if filter_status == "pending" and bug_status != "pending":
                continue
            if filter_status == "in_progress" and bug_status != "in_progress":
                continue
            if filter_status != "all" and filter_status not in ["pending", "in_progress"]:
                if bug_status != filter_status:
                    continue

            tasks.append(TaskForGroup(
                job_id=job_id,
                bug_index=idx,
                url=bug.get("url", ""),
                status=bug_status,
                config=config,
            ))

    return TasksForGroupResponse(tasks=tasks, total=len(tasks))


@router.post(
    "/tasks/{job_id}/bugs/{bug_index}/status",
    response_model=BugStatusUpdateResponse,
)
async def update_bug_status(
    job_id: str,
    bug_index: int,
    payload: BugStatusUpdateRequest,
):
    """Update the status of a specific bug in a job.

    Target groups should call this to report progress on bug fixes.
    """
    async with _cache_lock:
        if job_id not in BATCH_JOBS_CACHE:
            raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")

        job = BATCH_JOBS_CACHE[job_id]
        bugs = job.get("bugs", [])

        if bug_index < 0 or bug_index >= len(bugs):
            raise HTTPException(
                status_code=400,
                detail=f"Bug index {bug_index} out of range (0-{len(bugs)-1})",
            )

        now = datetime.now(timezone.utc).isoformat()
        bug = bugs[bug_index]

        # Update bug status
        bug["status"] = payload.status
        if payload.error:
            bug["error"] = payload.error

        # Update timestamps
        if payload.status == "in_progress" and not bug.get("started_at"):
            bug["started_at"] = now
        if payload.status in ["completed", "failed", "skipped"]:
            bug["completed_at"] = now

        job["updated_at"] = now

        # Calculate overall job status
        completed = sum(1 for b in bugs if b["status"] == "completed")
        failed = sum(1 for b in bugs if b["status"] == "failed")
        in_progress = sum(1 for b in bugs if b["status"] == "in_progress")
        pending = sum(1 for b in bugs if b["status"] == "pending")

        if in_progress > 0:
            job_status = "running"
        elif pending > 0 and (completed > 0 or failed > 0):
            job_status = "running"
        elif pending == 0 and in_progress == 0:
            job_status = "completed" if failed == 0 else "failed"
        else:
            job_status = job.get("status", "started")

        job["status"] = job_status

    return BugStatusUpdateResponse(
        success=True,
        job_id=job_id,
        bug_index=bug_index,
        new_status=payload.status,
        job_status=job_status,
    )


# --- SSE Progress Streaming ---


import json


def push_job_event(job_id: str, event_type: str, data: Dict[str, Any]) -> None:
    """Push an SSE event to connected clients for a job.

    Thread-safe: reads JOB_SSE_QUEUES snapshot to avoid races with SSE cleanup.

    Args:
        job_id: The batch job ID
        event_type: Event type (bug_started, bug_completed, bug_failed, job_done, db_warning)
        data: Event data payload
    """
    queue = JOB_SSE_QUEUES.get(job_id)
    if queue:
        try:
            queue.put_nowait({"event": event_type, "data": data})
            logger.debug(f"Job {job_id}: Pushed SSE event {event_type}")
        except asyncio.QueueFull:
            logger.warning(f"Job {job_id}: SSE queue full, dropping event {event_type}")
        except Exception:
            # Queue may have been removed between get() and put_nowait()
            pass


async def sse_job_generator(job_id: str):
    """Generate SSE events for a batch job.

    Yields:
        SSE formatted event strings
    """
    logger.info(f"Job {job_id}: SSE client connected")
    queue: asyncio.Queue = asyncio.Queue(maxsize=1000)
    async with _sse_lock:
        JOB_SSE_QUEUES[job_id] = queue

    try:
        # Send initial job state
        async with _cache_lock:
            job = BATCH_JOBS_CACHE.get(job_id)
        if job:
            yield f"event: job_state\ndata: {json.dumps(job, default=str)}\n\n"

        # Stream events
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=30.0)
                if event is None:  # Sentinel to stop
                    break
                yield f"event: {event['event']}\ndata: {json.dumps(event['data'], default=str)}\n\n"

                # Stop streaming after job completion
                if event.get("event") == "job_done":
                    break
            except asyncio.TimeoutError:
                # Send keepalive
                yield ": keepalive\n\n"
    finally:
        async with _sse_lock:
            JOB_SSE_QUEUES.pop(job_id, None)
        logger.info(f"Job {job_id}: SSE client disconnected")


@router.get("/batch-bug-fix/{job_id}/stream")
async def stream_batch_job_progress(job_id: str):
    """Stream real-time progress updates for a batch bug fix job via SSE.

    Events:
    - job_state: Initial job state when connected
    - bug_started: When a bug fix starts (data: {bug_index, url})
    - bug_step_started: When a step begins (data: {bug_index, step, label, attempt?})
    - bug_step_completed: When a step completes (data: {bug_index, step, label, status, duration_ms, output_preview, attempt?})
    - bug_step_failed: When a step fails (data: {bug_index, step, label, error, attempt?})
    - bug_completed: When a bug fix completes (data: {bug_index, url})
    - bug_failed: When a bug fix fails (data: {bug_index, url, error})
    - job_done: When the entire job completes (data: {status, completed, failed})

    Usage:
        const sse = new EventSource('/api/v2/cccc/batch-bug-fix/job_xxx/stream');
        sse.addEventListener('bug_step_started', (e) => console.log(JSON.parse(e.data)));
    """
    async with _cache_lock:
        if job_id not in BATCH_JOBS_CACHE:
            raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")

    return StreamingResponse(
        sse_job_generator(job_id),
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


@router.post("/batch-bug-fix/{job_id}/cancel", response_model=JobControlResponse)
async def cancel_batch_job(job_id: str):
    """Cancel a running batch bug fix job.

    Terminates the workflow execution and marks the job as cancelled.
    Bugs that were in progress will be marked as failed.
    """
    # Check cache first, then database
    async with _cache_lock:
        job = BATCH_JOBS_CACHE.get(job_id)
    if not job:
        async with get_session_ctx() as session:
            repo = BatchJobRepository(session)
            db_job = await repo.get(job_id)
            if db_job:
                job = _db_job_to_dict(db_job)

    if not job:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")

    current_status = job.get("status", "")
    if current_status in ["completed", "failed", "cancelled"]:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot cancel job with status '{current_status}'"
        )

    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()

    # Cancel the asyncio task if it exists
    async with _tasks_lock:
        workflow_task = WORKFLOW_TASKS.get(job_id)
    if workflow_task and not workflow_task.done():
        workflow_task.cancel()
        # Wait for cancellation to propagate before cleaning up state
        try:
            await asyncio.wait_for(asyncio.shield(workflow_task), timeout=5.0)
        except (asyncio.CancelledError, asyncio.TimeoutError, Exception):
            pass
        logger.info(f"Job {job_id}: Workflow task cancelled")

    # Update cache
    async with _cache_lock:
        if job_id in BATCH_JOBS_CACHE:
            cache_job = BATCH_JOBS_CACHE[job_id]
            cache_job["status"] = "cancelled"
            cache_job["updated_at"] = now_iso
            # Mark in-progress bugs as failed
            for bug in cache_job.get("bugs", []):
                if bug["status"] == "in_progress":
                    bug["status"] = "failed"
                    bug["error"] = "Job cancelled"
                    bug["completed_at"] = now_iso

    # Update database
    try:
        async with get_session_ctx() as session:
            repo = BatchJobRepository(session)
            await repo.update_status(job_id, "cancelled")
            # Update in-progress bugs
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
        push_job_event(job_id, "db_warning", {
            "message": f"Cancel DB sync failed: {e}",
            "timestamp": now_iso,
        })

    # Push SSE event
    push_job_event(job_id, "job_done", {
        "status": "cancelled",
        "message": "Job cancelled by user",
        "timestamp": now_iso,
    })

    # Clean up
    async with _tasks_lock:
        WORKFLOW_TASKS.pop(job_id, None)

    return JobControlResponse(
        success=True,
        job_id=job_id,
        status="cancelled",
        message="Job cancelled successfully",
    )


# --- Jira Integration Endpoints ---


class JiraQueryRequest(BaseModel):
    """Request for POST /api/v2/cccc/jira/query."""
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
    """Response for POST /api/v2/cccc/jira/query."""
    bugs: List[JiraBugInfo]
    total: int
    jql: str


class JiraErrorResponse(BaseModel):
    """Error response for Jira API failures."""
    error: str
    error_type: Literal["auth_failed", "jql_error", "connection_error", "unknown"]
    details: Optional[str] = None


@router.post(
    "/jira/query",
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
    # Using GET with query params to avoid v3 POST pagination bugs
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
    # Note: NOT logging credentials

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(search_url, headers=headers, params=params)

            # Handle error responses
            if response.status_code == 401:
                raise HTTPException(
                    status_code=401,
                    detail={
                        "error": "Authentication failed. Check email and API token.",
                        "error_type": "auth_failed",
                    },
                )

            if response.status_code == 400:
                # JQL syntax error
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

        # Extract status
        status_obj = fields.get("status", {})
        status = status_obj.get("name", "Unknown") if status_obj else "Unknown"

        # Extract priority
        priority_obj = fields.get("priority")
        priority = priority_obj.get("name") if priority_obj else None

        # Extract assignee
        assignee_obj = fields.get("assignee")
        assignee = assignee_obj.get("displayName") if assignee_obj else None

        # Build issue URL
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
