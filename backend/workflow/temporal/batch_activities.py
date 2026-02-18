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

# Re-export from sub-modules for backward compatibility
from .sse_events import (  # noqa: F401
    NODE_TO_STEP,
    _push_event,
    _setup_sync_event_pusher,
    _periodic_heartbeat,
    _record_next_step_start,
)
from .git_operations import (  # noqa: F401
    _extract_jira_key,
    _git_is_repo,
    _git_has_changes,
    _git_commit_bug_fix,
    _git_revert_changes,
    _git_change_summary,
    _prescan_closed_bugs,
    _preflight_check,
    _JIRA_RESOLVED_CATEGORIES,
    _jira_get_status,
    _git_run,
)
from .state_sync import (  # noqa: F401
    _db_index,
    _update_job_status,
    _reset_stale_bugs,
    _update_bug_status_db,
    _persist_bug_steps,
    _sync_incremental_results,
    _sync_final_results,
)

from ..settings import BATCH_HEARTBEAT_INTERVAL, BATCH_DB_SYNC_MAX_ATTEMPTS, FAILURE_POLICY  # noqa: F401

logger = logging.getLogger("workflow.temporal.batch_activities")


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
    bug_index_offset = params.get("bug_index_offset", 0)

    logger.info(
        f"Job {job_id}: Starting batch bugfix activity with {len(jira_urls)} bugs"
    )

    # Ensure node types are registered
    import workflow.nodes.base  # noqa: F401
    import workflow.nodes.agents  # noqa: F401

    # Configure the sync event pusher for AI thinking callbacks
    _setup_sync_event_pusher()

    # Pre-flight environment check
    preflight_ok, preflight_issues = await _preflight_check(cwd, config, job_id)
    if not preflight_ok:
        error_msg = "Pre-flight 检查失败:\n" + "\n".join(f"  - {e}" for e in preflight_issues)
        logger.error(f"Job {job_id}: {error_msg}")
        await _update_job_status(job_id, "failed", error=error_msg)
        await _push_event(job_id, "preflight_failed", {
            "errors": preflight_issues,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        await _push_event(job_id, "job_done", {
            "status": "failed",
            "error": error_msg,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        return {"success": False, "job_id": job_id, "error": error_msg}

    # Push preflight success with any warnings
    if preflight_issues:
        await _push_event(job_id, "preflight_passed", {
            "warnings": preflight_issues,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

    # Update job status to running in DB (also needed on retry attempts
    # where a previous attempt may have set status to "cancelled")
    await _update_job_status(job_id, "running")

    # On retry attempts, reset any stale in_progress bugs back to pending
    attempt = activity.info().attempt
    if attempt > 1:
        logger.info(f"Job {job_id}: Retry attempt {attempt}, resetting stale bug statuses")
        await _reset_stale_bugs(job_id, len(jira_urls))

    # Pre-scan Jira statuses: skip closed/resolved bugs (T105)
    closed_indices = await _prescan_closed_bugs(jira_urls, job_id)
    index_map: Optional[List[int]] = None
    active_urls = jira_urls

    if closed_indices:
        now_scan = datetime.now(timezone.utc)
        now_scan_iso = now_scan.isoformat()

        for ci in sorted(closed_indices):
            db_ci = ci + bug_index_offset
            jira_key = _extract_jira_key(jira_urls[ci])

            # Mark as skipped in DB
            await _update_bug_status_db(
                job_id, db_ci, "skipped",
                error=f"Jira issue {jira_key} 已关闭，跳过",
                completed_at=now_scan,
            )
            # Push SSE events
            await _push_event(job_id, "bug_step_completed", {
                "bug_index": db_ci,
                "step": "jira_check",
                "label": "Jira 状态检查",
                "node_label": "Jira 状态检查",
                "status": "completed",
                "output_preview": f"{jira_key} 已关闭 (Done)，跳过修复",
                "timestamp": now_scan_iso,
            })
            await _push_event(job_id, "bug_skipped", {
                "bug_index": db_ci,
                "url": jira_urls[ci],
                "reason": f"Jira issue {jira_key} 已关闭",
                "timestamp": now_scan_iso,
            })

        # Build active URL list and index map
        active_indices = [
            i for i in range(len(jira_urls)) if i not in closed_indices
        ]

        if not active_indices:
            # All bugs are closed — job done
            logger.info(
                f"Job {job_id}: All {len(jira_urls)} bugs are resolved, "
                f"nothing to do"
            )
            await _update_job_status(job_id, "completed")
            await _push_event(job_id, "job_done", {
                "status": "completed",
                "completed": 0,
                "failed": 0,
                "skipped": len(jira_urls),
                "total": len(jira_urls),
                "message": "所有 Bug 均已关闭，无需修复",
                "timestamp": now_scan_iso,
            })
            return {"success": True, "job_id": job_id, "all_skipped": True}

        active_urls = [jira_urls[i] for i in active_indices]
        index_map = [i + bug_index_offset for i in active_indices]
        logger.info(
            f"Job {job_id}: Skipped {len(closed_indices)} closed bugs, "
            f"processing {len(active_urls)} active bugs"
        )

    # Start background heartbeat task — sends heartbeat every 60s
    # so Temporal knows the activity is alive during long Claude CLI calls
    heartbeat_task = asyncio.create_task(
        _periodic_heartbeat(job_id, interval_seconds=60)
    )

    # Mark first active bug as in_progress
    now = datetime.now(timezone.utc)
    if active_urls:
        first_db_index = _db_index(0, bug_index_offset, index_map)
        await _update_bug_status_db(job_id, first_db_index, "in_progress", started_at=now)
        await _push_event(job_id, "bug_started", {
            "bug_index": first_db_index,
            "url": active_urls[0],
            "timestamp": now.isoformat(),
        })

    try:
        final_state = await _execute_workflow(
            job_id, active_urls, cwd, config, bug_index_offset, index_map,
        )

        # Final sync
        pre_skipped = len(closed_indices) if closed_indices else 0
        await _sync_final_results(
            job_id, final_state, active_urls, bug_index_offset,
            index_map, pre_skipped,
        )

        logger.info(f"Job {job_id}: Batch bugfix activity completed")
        return {"success": True, "job_id": job_id}

    except asyncio.CancelledError:
        logger.info(f"Job {job_id}: Activity cancelled")
        if await _git_is_repo(cwd):
            if await _git_has_changes(cwd):
                logger.info(f"Job {job_id}: Reverting uncommitted changes after cancel")
                await _git_revert_changes(cwd, job_id, "cancelled")
        await _update_job_status(job_id, "cancelled")
        await _push_event(job_id, "job_done", {
            "status": "cancelled",
            "message": "Job cancelled",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        return {"success": False, "job_id": job_id, "cancelled": True}

    except Exception as e:
        logger.error(f"Job {job_id}: Activity failed: {e}")
        if await _git_is_repo(cwd):
            if await _git_has_changes(cwd):
                logger.info(f"Job {job_id}: Reverting uncommitted changes after error")
                await _git_revert_changes(cwd, job_id, "error")
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
    bug_index_offset: int = 0,
    index_map: Optional[List[int]] = None,
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
    from workflow.templates import load_template, template_to_workflow_definition

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

    # Git isolation: check if cwd is a git repo
    git_enabled = await _git_is_repo(cwd)
    if git_enabled:
        logger.info(f"Job {job_id}: Git isolation enabled for {cwd}")
    else:
        logger.warning(
            f"Job {job_id}: Git isolation disabled — {cwd} is not a git repo"
        )

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
            if node_id in ["update_success", "update_failure", "check_more_bugs"]:
                bug_index = max(0, bug_index - 1)

            db_bug_index = _db_index(bug_index, bug_index_offset, index_map)

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

                duration_ms = None
                start_key = f"{bug_index}:{node_id}"
                if start_key in node_start_times:
                    duration_ms = (
                        (now - node_start_times[start_key]).total_seconds()
                        * 1000
                    )

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

                await _push_event(job_id, "bug_step_completed", {
                    "bug_index": db_bug_index,
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

            _record_next_step_start(
                job_id, node_id, bug_index, state, node_start_times,
                bug_index_offset, index_map,
            )

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
                        bug_index_offset,
                        index_map,
                    )
                    last_synced_index = len(current_results) - 1
                    logger.info(
                        f"Job {job_id}: Synced result "
                        f"{last_synced_index + 1}/{len(jira_urls)}"
                    )

                    steps = bug_steps.get(last_synced_index)
                    if steps:
                        await _persist_bug_steps(
                            job_id, _db_index(last_synced_index, bug_index_offset, index_map), steps,
                        )

                    # --- failure_policy "stop": abort on first failure ---
                    fp = config.get("failure_policy", "skip")
                    if fp == "stop" and last_synced_index < len(current_results):
                        latest = current_results[last_synced_index]
                        if latest.get("status") == "failed":
                            logger.info(
                                f"Job {job_id}: failure_policy=stop — "
                                f"aborting after bug {last_synced_index} failed"
                            )
                            await _push_event(job_id, "workflow_error", {
                                "message": (
                                    f"failure_policy=stop: Bug {last_synced_index} "
                                    f"修复失败，终止剩余 Bug 处理"
                                ),
                                "timestamp": datetime.now(timezone.utc).isoformat(),
                            })
                            return state

            # --- Git isolation: commit or revert after each bug ---
            if git_enabled and node_id == "update_success":
                bug_url = jira_urls[bug_index] if bug_index < len(jira_urls) else ""

                change_summary = await _git_change_summary(cwd, job_id)
                if change_summary:
                    preview = (
                        f"{change_summary['files_changed']} 文件变更 "
                        f"(+{change_summary['insertions']} "
                        f"-{change_summary['deletions']})"
                    )
                    if change_summary.get("new_files", 0) > 0:
                        preview += f", {change_summary['new_files']} 新文件"
                    files = change_summary["file_list"]
                    if files:
                        preview += "\n" + "\n".join(
                            f"  {f}" for f in files[:5]
                        )
                        if len(files) > 5:
                            preview += f"\n  ... 等 {len(files) - 5} 个文件"
                    await _push_event(job_id, "bug_step_completed", {
                        "bug_index": db_bug_index,
                        "step": "code_summary",
                        "label": "代码变更摘要",
                        "node_label": "代码变更摘要",
                        "status": "completed",
                        "output_preview": preview,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    })

                committed = await _git_commit_bug_fix(cwd, bug_url, job_id)
                if committed:
                    await _push_event(job_id, "bug_step_completed", {
                        "bug_index": db_bug_index,
                        "step": "git_commit",
                        "label": "Git 提交",
                        "node_label": "Git 提交",
                        "status": "completed",
                        "output_preview": f"fix: {_extract_jira_key(bug_url)}",
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    })

            elif git_enabled and node_id == "update_failure":
                bug_url = jira_urls[bug_index] if bug_index < len(jira_urls) else ""
                jira_key = _extract_jira_key(bug_url)
                reverted = await _git_revert_changes(cwd, job_id, jira_key)
                if reverted:
                    await _push_event(job_id, "bug_step_completed", {
                        "bug_index": db_bug_index,
                        "step": "git_revert",
                        "label": "Git 还原",
                        "node_label": "Git 还原",
                        "status": "completed",
                        "output_preview": f"已还原 {jira_key} 的失败修改",
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    })

    # Final safety net: revert any uncommitted changes left over
    if git_enabled and await _git_has_changes(cwd):
        logger.warning(f"Job {job_id}: Reverting leftover uncommitted changes")
        await _git_revert_changes(cwd, job_id, "cleanup")

    state["success"] = True
    return state
