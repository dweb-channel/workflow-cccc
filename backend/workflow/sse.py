"""SSE Event Utilities for Workflow Execution

Provides push_sse_event and notify_node_status for real-time
frontend updates during workflow execution.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, TypedDict

import os

import httpx

from .logging_config import get_worker_logger
from .settings import SSE_HTTP_MAX_CONNECTIONS, SSE_HTTP_MAX_KEEPALIVE, SSE_HTTP_TIMEOUT

# API base URL for pushing SSE events (Worker → FastAPI)
# Use 127.0.0.1 instead of localhost to avoid IPv6 timeout issues
# Override via env var for Docker (e.g. http://backend:8000)
API_BASE_URL = os.getenv("API_BASE_URL", "http://127.0.0.1:8000")

logger = get_worker_logger()

# Shared httpx client with connection pooling — avoids creating a new
# TCP connection for every SSE event push (hundreds per workflow run).
_http_client: Optional[httpx.AsyncClient] = None


async def _get_http_client() -> httpx.AsyncClient:
    """Get or create the shared httpx client."""
    global _http_client
    if _http_client is None or _http_client.is_closed:
        _http_client = httpx.AsyncClient(
            timeout=SSE_HTTP_TIMEOUT,
            limits=httpx.Limits(
                max_connections=SSE_HTTP_MAX_CONNECTIONS,
                max_keepalive_connections=SSE_HTTP_MAX_KEEPALIVE,
            ),
        )
    return _http_client


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
    logger.info(f"Pushing event: {event_type} to {url}")

    try:
        client = await _get_http_client()
        resp = await client.post(url, json=payload)
        logger.info(f"Response: {resp.status_code}")
    except Exception as e:
        # Log error but don't fail workflow
        logger.error(f"Failed to push event: {e}")


async def notify_node_status(run_id: str, node: str, status: str, output: Any = None) -> None:
    """Notify frontend about node status change.

    Args:
        run_id: The workflow run ID
        node: Node name
        status: Status (running, completed, error)
        output: Optional output data for completed status
    """
    timestamp = datetime.now(timezone.utc).isoformat()

    # Push status update — use node_started/node_completed for frontend compatibility
    if status == "running":
        event_type = "node_started"
    elif status == "completed":
        event_type = "node_completed"
    else:
        event_type = "node_update"

    await push_sse_event(run_id, event_type, {
        "node_id": node,
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
