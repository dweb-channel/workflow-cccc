"""Temporal Activity for Batch Bug Fix Execution.

Contains the long-running activity that executes the batch bug fix
workflow via LangGraph. Pushes SSE events via HTTP POST to the API
server and persists results directly to the database.

This runs in the Temporal Worker process, completely isolated from
the FastAPI event loop.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from temporalio import activity

logger = logging.getLogger("workflow.temporal.batch_activities")

# Node ID -> user-facing step mapping (None = internal node, not exposed to UI)
NODE_TO_STEP: Dict[str, Optional[tuple]] = {
    "get_current_bug": ("fetching", "获取 Bug 信息"),
    "fix_bug_peer": ("fixing", "修复 Bug"),
    "verify_fix": ("verifying", "验证修复结果"),
    "check_verify_result": None,
    "check_retry": None,
    "increment_retry": ("retrying", "准备重试"),
    "update_success": ("completed", "修复完成"),
    "update_failure": ("failed", "修复失败"),
    "check_more_bugs": None,
    "input_node": None,
    "output_node": None,
}


# --- SSE Push Helpers ---


async def _push_event(job_id: str, event_type: str, data: Dict[str, Any]) -> None:
    """Push an SSE event to the API server via HTTP POST.

    Uses the existing push_sse_event from workflow/sse.py which POSTs to
    /api/internal/events/{run_id}. Non-blocking: logs errors but never
    fails the workflow.
    """
    from ..sse import push_sse_event

    try:
        await push_sse_event(job_id, event_type, data)
    except Exception as e:
        logger.error(f"Job {job_id}: Failed to push SSE event {event_type}: {e}")


def _setup_sync_event_pusher() -> None:
    """Configure agents.py to push events via HTTP POST (fire-and-forget).

    The on_event callback in agents.py is synchronous, so we create
    a sync wrapper that schedules async HTTP POST calls on the event loop.
    """
    from ..nodes.agents import set_job_event_pusher

    def sync_push(job_id: str, event_type: str, data: Dict[str, Any]) -> None:
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(_push_event(job_id, event_type, data))
        except RuntimeError:
            pass  # No event loop running, skip

    set_job_event_pusher(sync_push)


# --- Heartbeat ---


async def _periodic_heartbeat(job_id: str, interval_seconds: int = 60) -> None:
    """Send periodic heartbeats to Temporal while the activity is running.

    This prevents heartbeat timeout during long-running Claude CLI calls.
    Runs as a background task and is cancelled when the activity completes.
    """
    while True:
        await asyncio.sleep(interval_seconds)
        try:
            activity.heartbeat(f"alive:job:{job_id}")
        except Exception:
            # Activity may have been cancelled; stop heartbeating
            return


# --- Main Activity ---


@activity.defn
async def execute_batch_bugfix_activity(params: dict) -> dict:
    """Execute the batch bug fix workflow as a Temporal activity.

    This is a long-running activity that:
    1. Loads the bug_fix_batch template
    2. Builds and executes the LangGraph workflow
    3. Pushes SSE events via HTTP POST for real-time UI updates
    4. Persists results to the database
    5. Sends heartbeats to keep the Temporal workflow alive

    Args:
        params: Dict with keys:
            - job_id: Unique job identifier
            - jira_urls: List of Jira bug URLs
            - cwd: Working directory for Claude CLI
            - config: Job configuration dict

    Returns:
        Dict with job results summary
    """
    job_id = params["job_id"]
    jira_urls = params["jira_urls"]
    cwd = params.get("cwd", ".")
    config = params.get("config", {})

    logger.info(
        f"Job {job_id}: Starting batch bugfix activity with {len(jira_urls)} bugs"
    )

    # Ensure node types are registered
    import workflow.nodes.base  # noqa: F401
    import workflow.nodes.agents  # noqa: F401

    # Configure the sync event pusher for AI thinking callbacks
    _setup_sync_event_pusher()

    # Update job status to running in DB (also needed on retry attempts
    # where a previous attempt may have set status to "cancelled")
    await _update_job_status(job_id, "running")

    # On retry attempts, reset any stale in_progress bugs back to pending
    attempt = activity.info().attempt
    if attempt > 1:
        logger.info(f"Job {job_id}: Retry attempt {attempt}, resetting stale bug statuses")
        await _reset_stale_bugs(job_id, len(jira_urls))

    # Start background heartbeat task — sends heartbeat every 60s
    # so Temporal knows the activity is alive during long Claude CLI calls
    heartbeat_task = asyncio.create_task(
        _periodic_heartbeat(job_id, interval_seconds=60)
    )

    # Mark first bug as in_progress
    now = datetime.now(timezone.utc)
    if jira_urls:
        await _update_bug_status_db(job_id, 0, "in_progress", started_at=now)
        await _push_event(job_id, "bug_started", {
            "bug_index": 0,
            "url": jira_urls[0],
            "timestamp": now.isoformat(),
        })

    try:
        final_state = await _execute_workflow(job_id, jira_urls, cwd, config)

        # Final sync
        await _sync_final_results(job_id, final_state, jira_urls)

        logger.info(f"Job {job_id}: Batch bugfix activity completed")
        return {"success": True, "job_id": job_id}

    except asyncio.CancelledError:
        logger.info(f"Job {job_id}: Activity cancelled")
        await _update_job_status(job_id, "cancelled")
        await _push_event(job_id, "job_done", {
            "status": "cancelled",
            "message": "Job cancelled",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        return {"success": False, "job_id": job_id, "cancelled": True}

    except Exception as e:
        logger.error(f"Job {job_id}: Activity failed: {e}")
        await _update_job_status(job_id, "failed", error=str(e))
        await _push_event(job_id, "job_done", {
            "status": "failed",
            "error": str(e),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        return {"success": False, "job_id": job_id, "error": str(e)}

    finally:
        heartbeat_task.cancel()
        try:
            await heartbeat_task
        except asyncio.CancelledError:
            pass


# --- Workflow Execution ---


async def _execute_workflow(
    job_id: str,
    jira_urls: List[str],
    cwd: str,
    config: Dict[str, Any],
) -> Dict[str, Any]:
    """Build and execute the LangGraph workflow with real-time tracking.

    Streams node completions, pushes SSE events, syncs to DB,
    and heartbeats to Temporal after each node.
    """
    from ..engine.graph_builder import (
        WorkflowDefinition,
        NodeConfig,
        EdgeDefinition,
        build_graph_from_config,
        detect_loops,
    )
    from app.templates import load_template, template_to_workflow_definition

    # Load workflow template
    template = load_template("bug_fix_batch")
    wf_dict = template_to_workflow_definition(template)

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
        "cwd": cwd,
        "current_index": 0,
        "retry_count": 0,
        "results": [],
        "context": {},
        "config": config,
        "run_id": job_id,
    }

    # Build and compile graph
    compiled_graph = build_graph_from_config(workflow_def)
    loops = detect_loops(workflow_def)

    recursion_limit = (
        workflow_def.max_iterations * len(workflow_def.nodes)
        + len(workflow_def.nodes)
    )
    graph_config = {"recursion_limit": recursion_limit} if loops else {}

    # Tracking state
    state = {**initial_state}
    last_synced_index = -1
    bug_steps: Dict[int, List[Dict[str, Any]]] = {}
    node_start_times: Dict[str, datetime] = {}

    logger.info(
        f"Job {job_id}: Executing workflow with {len(jira_urls)} bugs, "
        f"max_iterations={workflow_def.max_iterations}"
    )

    # Execute with streaming to capture each node completion
    async for event in compiled_graph.astream(state, config=graph_config):
        for node_id, node_output in event.items():
            # Merge state
            if isinstance(node_output, dict):
                for key, value in node_output.items():
                    state[key] = value

            # Heartbeat to Temporal after each node completion
            activity.heartbeat(
                f"node:{node_id}:bug:{state.get('current_index', 0)}"
            )

            # --- Step-level SSE events ---
            bug_index = state.get("current_index", 0)
            # After update_success/update_failure, current_index has been
            # incremented, so the bug that just completed is at index - 1
            if node_id in ["update_success", "update_failure", "check_more_bugs"]:
                bug_index = max(0, bug_index - 1)

            step_info = NODE_TO_STEP.get(node_id)
            now = datetime.now(timezone.utc)
            now_iso = now.isoformat()

            if step_info is not None:
                step_name, step_label = step_info
                attempt = (
                    state.get("retry_count", 0) + 1
                    if step_name in ("fixing", "verifying", "retrying")
                    else None
                )

                # Calculate duration
                duration_ms = None
                start_key = f"{bug_index}:{node_id}"
                if start_key in node_start_times:
                    duration_ms = (
                        (now - node_start_times[start_key]).total_seconds()
                        * 1000
                    )

                # Extract output preview from the node-specific result
                actual_result = (
                    node_output.get(node_id, {})
                    if isinstance(node_output, dict)
                    else {}
                )
                if not isinstance(actual_result, dict):
                    actual_result = {}

                output_preview = None
                if "result" in actual_result:
                    resp = actual_result["result"]
                    if isinstance(resp, str) and len(resp) > 0:
                        output_preview = (
                            resp[:500] + ("..." if len(resp) > 500 else "")
                        )
                elif "message" in actual_result:
                    msg = actual_result["message"]
                    if isinstance(msg, str) and len(msg) > 0:
                        output_preview = (
                            msg[:500] + ("..." if len(msg) > 500 else "")
                        )

                # Determine step status
                step_status = "completed"
                step_error = None
                if step_name == "failed":
                    step_status = "failed"
                elif isinstance(actual_result, dict):
                    if actual_result.get("success") is False:
                        step_status = "failed"
                        step_error = output_preview
                    elif actual_result.get("verified") is False:
                        step_status = "failed"
                        step_error = output_preview

                # Build step record
                step_record: Dict[str, Any] = {
                    "step": node_id,
                    "label": step_label,
                    "status": step_status,
                    "started_at": node_start_times.get(
                        start_key, now
                    ).isoformat(),
                    "completed_at": now_iso,
                    "duration_ms": (
                        round(duration_ms, 1) if duration_ms else None
                    ),
                    "output_preview": output_preview,
                    "error": step_error,
                }
                if attempt is not None:
                    step_record["attempt"] = attempt

                bug_steps.setdefault(bug_index, []).append(step_record)

                # Push bug_step_completed SSE event
                await _push_event(job_id, "bug_step_completed", {
                    "bug_index": bug_index,
                    "step": node_id,
                    "label": step_label,
                    "node_label": step_label,
                    "status": step_status,
                    "duration_ms": (
                        round(duration_ms, 1) if duration_ms else None
                    ),
                    "output_preview": output_preview,
                    "error": step_error,
                    "attempt": attempt,
                    "timestamp": now_iso,
                })

            # Predict and record next step start
            _record_next_step_start(
                job_id, node_id, bug_index, state, node_start_times,
            )

            # Sync results when update_success/update_failure completes
            if (
                "results" in node_output
                or node_id in ["update_success", "update_failure"]
            ):
                current_results = state.get("results", [])
                if not isinstance(current_results, list):
                    nested = node_output.get(node_id, {})
                    if isinstance(nested, dict):
                        current_results = nested.get("results", [])

                if (
                    isinstance(current_results, list)
                    and len(current_results) > last_synced_index + 1
                ):
                    await _sync_incremental_results(
                        job_id,
                        jira_urls,
                        current_results,
                        last_synced_index + 1,
                    )
                    last_synced_index = len(current_results) - 1
                    logger.info(
                        f"Job {job_id}: Synced result "
                        f"{last_synced_index + 1}/{len(jira_urls)}"
                    )

                    # Persist steps for completed bug
                    steps = bug_steps.get(last_synced_index)
                    if steps:
                        await _persist_bug_steps(
                            job_id, last_synced_index, steps,
                        )

    state["success"] = True
    return state


def _record_next_step_start(
    job_id: str,
    completed_node_id: str,
    bug_index: int,
    state: Dict[str, Any],
    node_start_times: Dict[str, datetime],
) -> None:
    """After a node completes, predict and record the start of the next step."""
    next_node_map: Dict[str, Optional[str]] = {
        "get_current_bug": "fix_bug_peer",
        "fix_bug_peer": "verify_fix",
        "verify_fix": None,
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
    attempt = (
        state.get("retry_count", 0) + 1
        if step_name in ("fixing", "verifying")
        else None
    )

    event_data: Dict[str, Any] = {
        "bug_index": bug_index,
        "step": next_node,
        "label": step_label,
        "node_label": step_label,
        "timestamp": now.isoformat(),
    }
    if attempt is not None:
        event_data["attempt"] = attempt

    # Fire-and-forget: schedule async push on event loop
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(_push_event(job_id, "bug_step_started", event_data))
    except RuntimeError:
        pass


# --- Database Helpers ---


async def _update_job_status(
    job_id: str,
    status: str,
    error: Optional[str] = None,
) -> None:
    """Update job status in database."""
    try:
        from app.database import get_session_ctx
        from app.batch_job_repository import BatchJobRepository

        async with get_session_ctx() as session:
            repo = BatchJobRepository(session)
            await repo.update_status(job_id, status, error=error)
        logger.info(f"Job {job_id}: DB status -> {status}")
    except Exception as e:
        logger.error(f"Job {job_id}: Failed to update status in DB: {e}")


async def _reset_stale_bugs(job_id: str, total_bugs: int) -> None:
    """Reset stale in_progress bugs back to pending on retry attempts.

    When a heartbeat timeout kills an attempt, bugs may be left in
    'in_progress' state. This resets them so the retry starts clean.
    """
    try:
        from app.database import get_session_ctx
        from app.batch_job_repository import BatchJobRepository

        async with get_session_ctx() as session:
            repo = BatchJobRepository(session)
            db_job = await repo.get(job_id)
            if db_job:
                for bug in db_job.bugs:
                    if bug.status == "in_progress":
                        await repo.update_bug_status(
                            job_id=job_id,
                            bug_index=bug.bug_index,
                            status="pending",
                        )
                        logger.info(
                            f"Job {job_id}: Reset bug {bug.bug_index} "
                            f"from in_progress to pending"
                        )
    except Exception as e:
        logger.error(f"Job {job_id}: Failed to reset stale bugs: {e}")


async def _update_bug_status_db(
    job_id: str,
    bug_index: int,
    status: str,
    error: Optional[str] = None,
    started_at: Optional[datetime] = None,
    completed_at: Optional[datetime] = None,
) -> None:
    """Update a single bug's status in database."""
    try:
        from app.database import get_session_ctx
        from app.batch_job_repository import BatchJobRepository

        async with get_session_ctx() as session:
            repo = BatchJobRepository(session)
            await repo.update_bug_status(
                job_id=job_id,
                bug_index=bug_index,
                status=status,
                error=error,
                started_at=started_at,
                completed_at=completed_at,
            )
    except Exception as e:
        logger.error(
            f"Job {job_id}: Failed to update bug {bug_index} status: {e}"
        )


async def _persist_bug_steps(
    job_id: str,
    bug_index: int,
    steps: List[Dict[str, Any]],
) -> None:
    """Persist step records for a completed bug to the database."""
    try:
        from app.database import get_session_ctx
        from app.batch_job_repository import BatchJobRepository

        async with get_session_ctx() as session:
            repo = BatchJobRepository(session)
            await repo.update_bug_steps(
                job_id=job_id,
                bug_index=bug_index,
                steps=steps,
            )
        logger.info(
            f"Job {job_id}: Persisted {len(steps)} steps for bug {bug_index}"
        )
    except Exception as e:
        logger.error(
            f"Job {job_id}: Failed to persist steps for bug {bug_index}: {e}"
        )


async def _sync_incremental_results(
    job_id: str,
    jira_urls: List[str],
    results: List[Dict[str, Any]],
    start_index: int,
) -> None:
    """Sync new results to database and push SSE events.

    Only processes results from start_index onwards (incremental).
    """
    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()

    for i in range(start_index, len(results)):
        if i >= len(jira_urls):
            break

        result = results[i]
        result_status = result.get("status", "failed")
        error_msg = None

        if result_status == "completed":
            await _push_event(job_id, "bug_completed", {
                "bug_index": i,
                "url": jira_urls[i],
                "timestamp": now_iso,
            })
        elif result_status == "failed":
            error_msg = result.get(
                "error", result.get("response", "Unknown error")
            )
            await _push_event(job_id, "bug_failed", {
                "bug_index": i,
                "url": jira_urls[i],
                "error": error_msg,
                "timestamp": now_iso,
            })
        elif result_status == "skipped":
            error_msg = result.get("error", "Skipped")
            await _push_event(job_id, "bug_failed", {
                "bug_index": i,
                "url": jira_urls[i],
                "error": error_msg,
                "skipped": True,
                "timestamp": now_iso,
            })

        # Update bug in DB
        await _update_bug_status_db(
            job_id, i, result_status,
            error=error_msg,
            completed_at=now,
        )

    # Mark next pending bug as in_progress
    next_index = len(results)
    if next_index < len(jira_urls):
        await _update_bug_status_db(
            job_id, next_index, "in_progress",
            started_at=now,
        )
        await _push_event(job_id, "bug_started", {
            "bug_index": next_index,
            "url": jira_urls[next_index],
            "timestamp": now_iso,
        })


async def _sync_final_results(
    job_id: str,
    final_state: Dict[str, Any],
    jira_urls: List[str],
) -> None:
    """Final sync — update all statuses and push job_done event."""
    results = final_state.get("results", [])
    now = datetime.now(timezone.utc)

    completed = sum(1 for r in results if r.get("status") == "completed")
    failed = sum(1 for r in results if r.get("status") == "failed")
    skipped = sum(1 for r in results if r.get("status") == "skipped")

    overall = "completed" if failed == 0 and skipped == 0 else "failed"

    try:
        from app.database import get_session_ctx
        from app.batch_job_repository import BatchJobRepository

        async with get_session_ctx() as session:
            repo = BatchJobRepository(session)
            for i, result in enumerate(results):
                await repo.update_bug_status(
                    job_id=job_id,
                    bug_index=i,
                    status=result.get("status", "failed"),
                    error=result.get("error"),
                    completed_at=now,
                )
            await repo.update_status(job_id, overall)
        logger.info(
            f"Job {job_id}: Final sync — {overall} "
            f"(completed={completed}, failed={failed}, skipped={skipped})"
        )
    except Exception as e:
        logger.error(f"Job {job_id}: Final DB sync failed: {e}")

    await _push_event(job_id, "job_done", {
        "status": overall,
        "completed": completed,
        "failed": failed,
        "skipped": skipped,
        "total": len(jira_urls),
        "timestamp": now.isoformat(),
    })
