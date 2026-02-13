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
import re
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


# --- Git Isolation Helpers ---


def _extract_jira_key(url: str) -> str:
    """Extract Jira issue key from URL.

    Examples:
        https://tssoft.atlassian.net/browse/XSZS-15463 → XSZS-15463
        XSZS-15463 → XSZS-15463
    """
    match = re.search(r"([A-Z][A-Z0-9]+-\d+)", url)
    return match.group(1) if match else url.rsplit("/", 1)[-1]


async def _git_run(cwd: str, *args: str) -> tuple[int, str]:
    """Run a git command and return (exit_code, stdout).

    Non-blocking async subprocess. Captures stderr into stdout.
    """
    try:
        proc = await asyncio.create_subprocess_exec(
            "git", *args,
            cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=30)
        return proc.returncode or 0, stdout.decode("utf-8", errors="replace").strip()
    except asyncio.TimeoutError:
        logger.warning(f"Git command timed out: git {' '.join(args)}")
        return 1, "timeout"
    except Exception as e:
        logger.warning(f"Git command failed: git {' '.join(args)}: {e}")
        return 1, str(e)


async def _git_is_repo(cwd: str) -> bool:
    """Check if cwd is inside a git repository."""
    code, _ = await _git_run(cwd, "rev-parse", "--is-inside-work-tree")
    return code == 0


async def _git_has_changes(cwd: str) -> bool:
    """Check if there are uncommitted changes (staged or unstaged)."""
    code, output = await _git_run(cwd, "status", "--porcelain")
    return code == 0 and len(output.strip()) > 0


async def _git_commit_bug_fix(cwd: str, jira_url: str, job_id: str) -> bool:
    """Stage all changes and commit with a descriptive message.

    Returns True if commit succeeded, False otherwise.
    """
    jira_key = _extract_jira_key(jira_url)

    if not await _git_has_changes(cwd):
        logger.info(f"Job {job_id}: No changes to commit for {jira_key}")
        return True  # No changes is not an error

    # Stage all changes in the working directory
    code, output = await _git_run(cwd, "add", ".")
    if code != 0:
        logger.error(f"Job {job_id}: git add failed for {jira_key}: {output}")
        return False

    # Commit with conventional commit format
    commit_msg = f"fix: {jira_key}\n\nAutomated fix by batch-bug-fix workflow\nJob: {job_id}"
    code, output = await _git_run(cwd, "commit", "-m", commit_msg)
    if code != 0:
        logger.error(f"Job {job_id}: git commit failed for {jira_key}: {output}")
        return False

    logger.info(f"Job {job_id}: Committed fix for {jira_key}")
    return True


async def _git_revert_changes(cwd: str, job_id: str, jira_key: str) -> bool:
    """Revert all uncommitted changes (tracked and untracked).

    Used when a bug fix fails after max retries.
    Returns True if revert succeeded.
    """
    if not await _git_has_changes(cwd):
        return True  # Nothing to revert

    # Revert tracked file changes
    code1, out1 = await _git_run(cwd, "checkout", ".")
    # Remove untracked files created during the fix attempt
    code2, out2 = await _git_run(cwd, "clean", "-fd")

    if code1 != 0:
        logger.error(f"Job {job_id}: git checkout failed for {jira_key}: {out1}")
    if code2 != 0:
        logger.error(f"Job {job_id}: git clean failed for {jira_key}: {out2}")

    success = code1 == 0 and code2 == 0
    if success:
        logger.info(f"Job {job_id}: Reverted changes for failed {jira_key}")
    return success


async def _git_change_summary(cwd: str, job_id: str) -> Optional[Dict[str, Any]]:
    """Collect code change summary before commit.

    Runs git diff --stat (tracked) and counts untracked files.
    Returns None if no changes.
    """
    if not await _git_has_changes(cwd):
        return None

    # Tracked file changes
    code, stat_output = await _git_run(cwd, "diff", "--stat")

    # Untracked (new) files
    code2, untracked_output = await _git_run(
        cwd, "ls-files", "--others", "--exclude-standard",
    )

    tracked_lines = (
        stat_output.strip().split("\n") if stat_output.strip() else []
    )
    untracked_files = [
        f for f in untracked_output.strip().split("\n") if f.strip()
    ] if untracked_output.strip() else []

    # Parse tracked file list from stat output (all lines except summary)
    tracked_files: List[str] = []
    insertions = 0
    deletions = 0

    if len(tracked_lines) > 1:
        for line in tracked_lines[:-1]:
            fname = line.strip().split("|")[0].strip()
            if fname:
                tracked_files.append(fname)

        summary_line = tracked_lines[-1]
        ins_match = re.search(r"(\d+) insertion", summary_line)
        del_match = re.search(r"(\d+) deletion", summary_line)
        if ins_match:
            insertions = int(ins_match.group(1))
        if del_match:
            deletions = int(del_match.group(1))

    all_files = tracked_files + untracked_files
    if not all_files:
        return None

    return {
        "files_changed": len(all_files),
        "insertions": insertions,
        "deletions": deletions,
        "new_files": len(untracked_files),
        "file_list": all_files[:10],
    }


# --- PR & Jira Helpers ---


async def _git_get_current_branch(cwd: str) -> Optional[str]:
    """Get the current branch name."""
    code, output = await _git_run(cwd, "rev-parse", "--abbrev-ref", "HEAD")
    return output if code == 0 and output else None


async def _git_create_fix_branch(
    cwd: str, jira_url: str, job_id: str,
) -> Optional[str]:
    """Create and checkout a fix branch for a specific bug.

    Branch name: fix/{jira-key-lowercase}
    Returns branch name or None on failure.
    """
    jira_key = _extract_jira_key(jira_url)
    branch_name = f"fix/{jira_key.lower()}"

    code, output = await _git_run(cwd, "checkout", "-b", branch_name)
    if code != 0:
        logger.warning(
            f"Job {job_id}: Failed to create branch {branch_name}: {output}"
        )
        return None

    logger.info(f"Job {job_id}: Created fix branch {branch_name}")
    return branch_name


async def _git_switch_branch(cwd: str, branch_name: str, job_id: str) -> bool:
    """Switch to an existing branch."""
    code, output = await _git_run(cwd, "checkout", branch_name)
    if code != 0:
        logger.warning(
            f"Job {job_id}: Failed to switch to {branch_name}: {output}"
        )
        return False
    return True


async def _git_delete_branch(cwd: str, branch_name: str, job_id: str) -> bool:
    """Delete a local branch (force)."""
    code, output = await _git_run(cwd, "branch", "-D", branch_name)
    if code != 0:
        logger.warning(
            f"Job {job_id}: Failed to delete branch {branch_name}: {output}"
        )
        return False
    logger.info(f"Job {job_id}: Deleted branch {branch_name}")
    return True


async def _git_recover_original_branch(cwd: str, job_id: str) -> None:
    """Recover from a fix/* branch back to the original branch.

    Best-effort: if we're on a fix/* branch after an error, switch back
    to the base branch and clean up. Used by outer exception handlers.
    """
    current = await _git_get_current_branch(cwd)
    if not current or not current.startswith("fix/"):
        return  # Not on a fix branch, nothing to recover

    # Find the base branch by checking what fix/* branched from
    code, base = await _git_run(
        cwd, "rev-parse", "--abbrev-ref", f"{current}@{{upstream}}"
    )
    if code != 0:
        # No upstream, try common defaults
        for candidate in ("main", "master", "develop"):
            code2, _ = await _git_run(cwd, "rev-parse", "--verify", candidate)
            if code2 == 0:
                base = candidate
                break
        else:
            logger.warning(
                f"Job {job_id}: Cannot determine base branch, staying on {current}"
            )
            return

    logger.info(f"Job {job_id}: Recovering from {current} to {base}")
    if await _git_has_changes(cwd):
        await _git_revert_changes(cwd, job_id, "recovery")
    await _git_switch_branch(cwd, base, job_id)
    await _git_delete_branch(cwd, current, job_id)


async def _git_push_and_create_pr(
    cwd: str,
    branch_name: str,
    base_branch: str,
    jira_url: str,
    job_id: str,
) -> Optional[str]:
    """Push fix branch and create a PR via gh CLI.

    Returns PR URL or None on failure. Best-effort: never fails the workflow.
    """
    jira_key = _extract_jira_key(jira_url)

    # Push branch to remote
    code, output = await _git_run(cwd, "push", "-u", "origin", branch_name)
    if code != 0:
        logger.warning(
            f"Job {job_id}: git push failed for {branch_name}: {output}"
        )
        return None

    # Create PR via gh CLI
    title = f"fix: {jira_key}"
    body = (
        f"Automated fix for [{jira_key}]({jira_url})\n\n"
        f"Job: `{job_id}`\n"
        f"Generated by batch-bug-fix workflow"
    )

    try:
        proc = await asyncio.create_subprocess_exec(
            "gh", "pr", "create",
            "--title", title,
            "--body", body,
            "--base", base_branch,
            "--head", branch_name,
            cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=30)
        pr_output = stdout.decode("utf-8", errors="replace").strip()

        if proc.returncode == 0:
            pr_url = pr_output.strip().split("\n")[-1]
            logger.info(f"Job {job_id}: Created PR for {jira_key}: {pr_url}")
            return pr_url
        else:
            logger.warning(
                f"Job {job_id}: gh pr create failed: {pr_output}"
            )
            return None

    except asyncio.TimeoutError:
        logger.warning(f"Job {job_id}: gh pr create timed out for {jira_key}")
        return None
    except FileNotFoundError:
        logger.warning(
            f"Job {job_id}: gh CLI not found, skipping PR creation"
        )
        return None
    except Exception as e:
        logger.warning(f"Job {job_id}: PR creation failed: {e}")
        return None


async def _jira_add_fix_comment(
    jira_url: str, pr_url: Optional[str], job_id: str,
) -> bool:
    """Add a fix comment to a Jira ticket. Best-effort.

    Requires env vars: JIRA_URL, JIRA_EMAIL, JIRA_API_TOKEN.
    Returns True if comment was added successfully.
    """
    import os

    jira_base = os.environ.get("JIRA_URL", "")
    email = os.environ.get("JIRA_EMAIL", "")
    token = os.environ.get("JIRA_API_TOKEN", "")

    if not all([jira_base, email, token]):
        logger.info(
            f"Job {job_id}: Jira credentials not configured, skipping comment"
        )
        return False

    jira_key = _extract_jira_key(jira_url)

    comment_text = (
        f"Automated fix applied by batch-bug-fix workflow (Job: {job_id})."
    )
    if pr_url:
        comment_text += f"\n\nPR: {pr_url}"

    try:
        import httpx
        import base64

        auth = base64.b64encode(f"{email}:{token}".encode()).decode()
        url = f"{jira_base.rstrip('/')}/rest/api/3/issue/{jira_key}/comment"
        headers = {
            "Authorization": f"Basic {auth}",
            "Content-Type": "application/json",
        }
        body = {
            "body": {
                "type": "doc",
                "version": 1,
                "content": [{
                    "type": "paragraph",
                    "content": [
                        {"type": "text", "text": comment_text},
                    ],
                }],
            }
        }

        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(url, headers=headers, json=body)
            if resp.status_code in (200, 201):
                logger.info(
                    f"Job {job_id}: Added Jira comment to {jira_key}"
                )
                return True
            else:
                logger.warning(
                    f"Job {job_id}: Jira comment failed for {jira_key}: "
                    f"{resp.status_code}"
                )
                return False

    except Exception as e:
        logger.warning(
            f"Job {job_id}: Jira comment failed for {jira_key}: {e}"
        )
        return False


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
    bug_index_offset = params.get("bug_index_offset", 0)

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
        await _update_bug_status_db(job_id, bug_index_offset, "in_progress", started_at=now)
        await _push_event(job_id, "bug_started", {
            "bug_index": bug_index_offset,
            "url": jira_urls[0],
            "timestamp": now.isoformat(),
        })

    try:
        final_state = await _execute_workflow(job_id, jira_urls, cwd, config, bug_index_offset)

        # Final sync
        await _sync_final_results(job_id, final_state, jira_urls, bug_index_offset)

        logger.info(f"Job {job_id}: Batch bugfix activity completed")
        return {"success": True, "job_id": job_id}

    except asyncio.CancelledError:
        logger.info(f"Job {job_id}: Activity cancelled")
        # Recover from fix branch + revert uncommitted changes
        if await _git_is_repo(cwd):
            await _git_recover_original_branch(cwd, job_id)
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
        # Recover from fix branch + revert uncommitted changes
        if await _git_is_repo(cwd):
            await _git_recover_original_branch(cwd, job_id)
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

    # PR/Jira integration: track branches for per-bug PRs
    original_branch: Optional[str] = None
    current_fix_branch: Optional[str] = None
    if git_enabled:
        original_branch = await _git_get_current_branch(cwd)

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

            # For retry runs, offset bug_index for DB/SSE operations
            db_bug_index = bug_index + bug_index_offset

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

            # Predict and record next step start
            _record_next_step_start(
                job_id, node_id, bug_index, state, node_start_times,
                bug_index_offset,
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
                        bug_index_offset,
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
                            job_id, last_synced_index + bug_index_offset, steps,
                        )

            # --- Per-bug fix branch creation ---
            if git_enabled and node_id == "get_current_bug" and original_branch:
                fix_bug_url = jira_urls[bug_index] if bug_index < len(jira_urls) else ""
                if fix_bug_url:
                    current_fix_branch = await _git_create_fix_branch(
                        cwd, fix_bug_url, job_id,
                    )

            # --- Git isolation: commit or revert after each bug ---
            if git_enabled and node_id == "update_success":
                bug_url = jira_urls[bug_index] if bug_index < len(jira_urls) else ""

                # Collect code change summary before commit
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

                    # --- PR creation (best-effort) ---
                    pr_url = None
                    if current_fix_branch and original_branch:
                        pr_url = await _git_push_and_create_pr(
                            cwd, current_fix_branch, original_branch,
                            bug_url, job_id,
                        )
                        if pr_url:
                            await _push_event(job_id, "bug_step_completed", {
                                "bug_index": db_bug_index,
                                "step": "pr_created",
                                "label": "创建 PR",
                                "node_label": "创建 PR",
                                "status": "completed",
                                "output_preview": pr_url,
                                "timestamp": datetime.now(timezone.utc).isoformat(),
                            })

                    # --- Jira comment (best-effort) ---
                    jira_ok = await _jira_add_fix_comment(bug_url, pr_url, job_id)
                    if jira_ok:
                        await _push_event(job_id, "bug_step_completed", {
                            "bug_index": db_bug_index,
                            "step": "jira_comment",
                            "label": "Jira 更新",
                            "node_label": "Jira 更新",
                            "status": "completed",
                            "output_preview": f"已添加评论到 {_extract_jira_key(bug_url)}",
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                        })

                    # Switch back to original branch for next bug
                    if current_fix_branch and original_branch:
                        await _git_switch_branch(cwd, original_branch, job_id)
                    current_fix_branch = None

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

                # Clean up fix branch after failure
                if current_fix_branch and original_branch:
                    await _git_switch_branch(cwd, original_branch, job_id)
                    await _git_delete_branch(cwd, current_fix_branch, job_id)
                current_fix_branch = None

    # Final safety net: clean up leftover fix branch
    if git_enabled and current_fix_branch and original_branch:
        current = await _git_get_current_branch(cwd)
        if current and current != original_branch:
            if await _git_has_changes(cwd):
                await _git_revert_changes(cwd, job_id, "cleanup")
            await _git_switch_branch(cwd, original_branch, job_id)
        await _git_delete_branch(cwd, current_fix_branch, job_id)

    # Final safety net: revert any uncommitted changes left over
    if git_enabled and await _git_has_changes(cwd):
        logger.warning(f"Job {job_id}: Reverting leftover uncommitted changes")
        await _git_revert_changes(cwd, job_id, "cleanup")

    state["success"] = True
    return state


def _record_next_step_start(
    job_id: str,
    completed_node_id: str,
    bug_index: int,
    state: Dict[str, Any],
    node_start_times: Dict[str, datetime],
    bug_index_offset: int = 0,
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
        "bug_index": bug_index + bug_index_offset,
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
) -> bool:
    """Update job status in database. Returns True on success."""
    try:
        from app.database import get_session_ctx
        from app.repositories.batch_job import BatchJobRepository

        async with get_session_ctx() as session:
            repo = BatchJobRepository(session)
            await repo.update_status(job_id, status, error=error)
        logger.info(f"Job {job_id}: DB status -> {status}")
        return True
    except Exception as e:
        logger.error(f"Job {job_id}: Failed to update status in DB: {e}")
        await _push_event(job_id, "db_sync_warning", {
            "message": f"数据库状态更新失败: {status}",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        return False


async def _reset_stale_bugs(job_id: str, total_bugs: int) -> None:
    """Reset stale in_progress bugs back to pending on retry attempts.

    When a heartbeat timeout kills an attempt, bugs may be left in
    'in_progress' state. This resets them so the retry starts clean.
    """
    try:
        from app.database import get_session_ctx
        from app.repositories.batch_job import BatchJobRepository

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
) -> bool:
    """Update a single bug's status in database. Returns True on success."""
    try:
        from app.database import get_session_ctx
        from app.repositories.batch_job import BatchJobRepository

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
        return True
    except Exception as e:
        logger.error(
            f"Job {job_id}: Failed to update bug {bug_index} status: {e}"
        )
        return False


async def _persist_bug_steps(
    job_id: str,
    bug_index: int,
    steps: List[Dict[str, Any]],
) -> bool:
    """Persist step records for a completed bug to the database. Returns True on success."""
    try:
        from app.database import get_session_ctx
        from app.repositories.batch_job import BatchJobRepository

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
        return True
    except Exception as e:
        logger.error(
            f"Job {job_id}: Failed to persist steps for bug {bug_index}: {e}"
        )
        return False


async def _sync_incremental_results(
    job_id: str,
    jira_urls: List[str],
    results: List[Dict[str, Any]],
    start_index: int,
    bug_index_offset: int = 0,
) -> None:
    """Sync new results to database and push SSE events.

    Only processes results from start_index onwards (incremental).
    bug_index_offset is added to array indices for DB/SSE bug_index
    (used by single-bug retry to map to the original bug position).
    """
    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()

    for i in range(start_index, len(results)):
        if i >= len(jira_urls):
            break

        db_i = i + bug_index_offset
        result = results[i]
        result_status = result.get("status", "failed")
        error_msg = None

        if result_status == "completed":
            await _push_event(job_id, "bug_completed", {
                "bug_index": db_i,
                "url": jira_urls[i],
                "timestamp": now_iso,
            })
        elif result_status == "failed":
            error_msg = result.get(
                "error", result.get("response", "Unknown error")
            )
            await _push_event(job_id, "bug_failed", {
                "bug_index": db_i,
                "url": jira_urls[i],
                "error": error_msg,
                "timestamp": now_iso,
            })
        elif result_status == "skipped":
            error_msg = result.get("error", "Skipped")
            await _push_event(job_id, "bug_failed", {
                "bug_index": db_i,
                "url": jira_urls[i],
                "error": error_msg,
                "skipped": True,
                "timestamp": now_iso,
            })

        # Update bug in DB
        db_ok = await _update_bug_status_db(
            job_id, db_i, result_status,
            error=error_msg,
            completed_at=now,
        )
        if not db_ok:
            await _push_event(job_id, "db_sync_warning", {
                "bug_index": db_i,
                "message": f"Bug {db_i} 状态同步失败，刷新页面后状态可能不准确",
                "timestamp": now_iso,
            })

    # Mark next pending bug as in_progress
    next_index = len(results)
    if next_index < len(jira_urls):
        db_next = next_index + bug_index_offset
        await _update_bug_status_db(
            job_id, db_next, "in_progress",
            started_at=now,
        )
        await _push_event(job_id, "bug_started", {
            "bug_index": db_next,
            "url": jira_urls[next_index],
            "timestamp": now_iso,
        })


async def _sync_final_results(
    job_id: str,
    final_state: Dict[str, Any],
    jira_urls: List[str],
    bug_index_offset: int = 0,
) -> None:
    """Final sync — update all statuses and push job_done event.

    For retry runs (bug_index_offset > 0), the overall job status is
    recomputed from ALL bugs in the DB, not just the current run's results.
    """
    results = final_state.get("results", [])
    now = datetime.now(timezone.utc)

    completed = sum(1 for r in results if r.get("status") == "completed")
    failed = sum(1 for r in results if r.get("status") == "failed")
    skipped = sum(1 for r in results if r.get("status") == "skipped")

    overall = "completed" if failed == 0 and skipped == 0 else "failed"
    db_sync_ok = False

    for attempt in range(2):  # 1 retry for transient DB failures
        try:
            from app.database import get_session_ctx
            from app.repositories.batch_job import BatchJobRepository

            async with get_session_ctx() as session:
                repo = BatchJobRepository(session)
                for i, result in enumerate(results):
                    await repo.update_bug_status(
                        job_id=job_id,
                        bug_index=i + bug_index_offset,
                        status=result.get("status", "failed"),
                        error=result.get("error"),
                        completed_at=now,
                    )

                # For retry runs, recompute overall status from ALL bugs in DB
                if bug_index_offset > 0:
                    db_job = await repo.get(job_id)
                    if db_job:
                        all_failed = sum(
                            1 for b in db_job.bugs
                            if b.status in ("failed", "skipped")
                        )
                        overall = "completed" if all_failed == 0 else "failed"

                await repo.update_status(job_id, overall)
            logger.info(
                f"Job {job_id}: Final sync — {overall} "
                f"(completed={completed}, failed={failed}, skipped={skipped})"
            )
            db_sync_ok = True
            break
        except Exception as e:
            logger.error(f"Job {job_id}: Final DB sync failed (attempt {attempt + 1}): {e}")
            if attempt == 0:
                await asyncio.sleep(1)  # Brief delay before retry

    event_data: Dict[str, Any] = {
        "status": overall,
        "completed": completed,
        "failed": failed,
        "skipped": skipped,
        "total": len(jira_urls),
        "timestamp": now.isoformat(),
    }
    if not db_sync_ok:
        event_data["db_sync_failed"] = True
        event_data["db_sync_message"] = "数据库同步失败，刷新页面后状态可能不准确"

    await _push_event(job_id, "job_done", event_data)
