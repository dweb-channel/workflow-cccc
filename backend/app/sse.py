"""SSE Infrastructure for real-time workflow execution updates.

Manages active SSE connections, event buffering, and the internal
event push endpoint used by Temporal activities.
"""

from __future__ import annotations

import asyncio
import json
import time

from fastapi import APIRouter
from pydantic import BaseModel

from workflow.logging_config import get_sse_logger

logger = get_sse_logger()

router = APIRouter()

# Store active SSE connections for each run
_active_streams: dict[str, asyncio.Queue] = {}
# Buffer events before SSE connection is established
# Each entry: {"events": [...], "created_at": float}
_event_buffers: dict[str, dict] = {}

# Buffer limits: prevent unbounded memory growth from orphaned jobs
_BUFFER_MAX_EVENTS = 200  # max events per job buffer
_BUFFER_MAX_AGE_SECS = 600  # discard buffers older than 10 minutes


def _cleanup_stale_buffers() -> None:
    """Remove event buffers that are too old (no SSE client ever connected)."""
    now = time.monotonic()
    stale = [
        rid for rid, buf in _event_buffers.items()
        if now - buf["created_at"] > _BUFFER_MAX_AGE_SECS
    ]
    for rid in stale:
        count = len(_event_buffers[rid]["events"])
        del _event_buffers[rid]
        logger.info(f"Cleaned up stale buffer for {rid} ({count} events)")


async def sse_event_generator(run_id: str):
    """Generate SSE events for a workflow run."""
    logger.info(f"Client connected for run_id: {run_id}")
    queue = asyncio.Queue()
    _active_streams[run_id] = queue

    try:
        # Flush any buffered events that arrived before SSE connection
        buf = _event_buffers.pop(run_id, None)
        buffered = buf["events"] if buf else []
        if buffered:
            logger.info(f"Flushing {len(buffered)} buffered events for {run_id}")
        for event in buffered:
            yield f"event: {event['event']}\ndata: {json.dumps(event['data'])}\n\n"

        # Stream updates from queue
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=30.0)
                if event is None:  # Sentinel to stop
                    break
                yield f"event: {event['event']}\ndata: {json.dumps(event['data'])}\n\n"

                # Check for workflow completion
                if event.get("event") == "workflow_complete":
                    break
            except asyncio.TimeoutError:
                # Send keepalive
                yield ": keepalive\n\n"
    finally:
        _active_streams.pop(run_id, None)
        _event_buffers.pop(run_id, None)


def push_node_event(run_id: str, event_type: str, data: dict):
    """Push an event to a running SSE stream.

    Called from workflow execution to update clients.
    If SSE connection not yet established, buffer events for later delivery.
    Buffer has size and age limits to prevent memory leaks.
    """
    event = {"event": event_type, "data": data}
    queue = _active_streams.get(run_id)
    if queue:
        queue.put_nowait(event)
        logger.info(f"Event sent to queue: {event_type} for {run_id}")
    else:
        # Buffer events until SSE connection is established
        if run_id not in _event_buffers:
            # Periodically clean up stale buffers
            _cleanup_stale_buffers()
            _event_buffers[run_id] = {"events": [], "created_at": time.monotonic()}

        buf = _event_buffers[run_id]
        if len(buf["events"]) < _BUFFER_MAX_EVENTS:
            buf["events"].append(event)
            logger.info(
                f"Event buffered ({len(buf['events'])}): {event_type} for {run_id}"
            )
        else:
            logger.warning(
                f"Buffer full ({_BUFFER_MAX_EVENTS}), dropping: {event_type} for {run_id}"
            )


# --- Internal API for Activity Callbacks ---


class InternalEventRequest(BaseModel):
    event_type: str
    data: dict


@router.post("/api/internal/events/{run_id}")
async def push_event_endpoint(run_id: str, payload: InternalEventRequest):
    """Internal endpoint for activities to push SSE events."""
    logger.info(f"Received event via API: {payload.event_type} for {run_id}")
    push_node_event(run_id, payload.event_type, payload.data)
    return {"status": "ok", "run_id": run_id}
