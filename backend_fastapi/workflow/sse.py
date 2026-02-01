"""SSE Event Utilities for Workflow Execution

Provides push_sse_event and notify_node_status for real-time
frontend updates during workflow execution.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, List, Optional, TypedDict

import httpx

from .logging_config import get_worker_logger

# API base URL for pushing SSE events
# Use 127.0.0.1 instead of localhost to avoid IPv6 timeout issues
API_BASE_URL = "http://127.0.0.1:8000"

logger = get_worker_logger()


class WorkflowState(TypedDict, total=False):
    """Generic workflow state used by Temporal activities."""
    request: str
    run_id: str


async def push_sse_event(run_id: str, event_type: str, data: dict) -> None:
    """Push SSE event to the API server.

    Args:
        run_id: The workflow run ID
        event_type: Event type (node_update, node_output, etc.)
        data: Event data payload
    """
    if not run_id:
        logger.warning(f"No run_id, skipping event: {event_type}")
        return

    url = f"{API_BASE_URL}/api/internal/events/{run_id}"
    payload = {"event_type": event_type, "data": data}
    logger.info(f"📤 Pushing event: {event_type} to {url}")

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(url, json=payload)
            logger.info(f"✅ Response: {resp.status_code}")
    except Exception as e:
        # Log error but don't fail workflow
        logger.error(f"❌ Failed to push event: {e}")


async def notify_node_status(run_id: str, node: str, status: str, output: Any = None) -> None:
    """Notify frontend about node status change.

    Args:
        run_id: The workflow run ID
        node: Node name
        status: Status (running, completed, error)
        output: Optional output data for completed status
    """
    timestamp = datetime.utcnow().isoformat() + "Z"

    # Push status update
    await push_sse_event(run_id, "node_update", {
        "node": node,
        "status": status,
        "timestamp": timestamp
    })

    # Push output if completed
    if status == "completed" and output is not None:
        await push_sse_event(run_id, "node_output", {
            "node": node,
            "output": output if isinstance(output, str) else json.dumps(output, ensure_ascii=False),
            "timestamp": timestamp
        })
