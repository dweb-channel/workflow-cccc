"""SSE event push helpers and heartbeat for Temporal activities.

These run in the Temporal Worker process and push events via HTTP POST
to the FastAPI API server for real-time UI updates.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from temporalio import activity

from ..settings import BATCH_HEARTBEAT_INTERVAL

logger = logging.getLogger("workflow.temporal.sse_events")

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


def _record_next_step_start(
    job_id: str,
    completed_node_id: str,
    bug_index: int,
    state: Dict[str, Any],
    node_start_times: Dict[str, datetime],
    bug_index_offset: int = 0,
    index_map: Optional[List[int]] = None,
) -> None:
    """After a node completes, predict and record the start of the next step."""
    from .state_sync import _db_index

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
        "bug_index": _db_index(bug_index, bug_index_offset, index_map),
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
