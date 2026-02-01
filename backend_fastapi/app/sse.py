"""SSE Infrastructure for real-time workflow execution updates.

Manages active SSE connections, event buffering, and the internal
event push endpoint used by Temporal activities.
"""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter
from pydantic import BaseModel

from workflow.logging_config import get_sse_logger

logger = get_sse_logger()

router = APIRouter()

# Store active SSE connections for each run
_active_streams: dict[str, asyncio.Queue] = {}
# Buffer events before SSE connection is established
_event_buffers: dict[str, list] = {}


async def sse_event_generator(run_id: str):
    """Generate SSE events for a workflow run."""
    logger.info(f"Client connected for run_id: {run_id}")
    queue = asyncio.Queue()
    _active_streams[run_id] = queue

    try:
        # Flush any buffered events that arrived before SSE connection
        buffered = _event_buffers.pop(run_id, [])
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
    """
    event = {"event": event_type, "data": data}
    queue = _active_streams.get(run_id)
    if queue:
        queue.put_nowait(event)
        logger.info(f"Event sent to queue: {event_type} for {run_id}")
    else:
        # Buffer events until SSE connection is established
        _event_buffers.setdefault(run_id, []).append(event)
        buffer_size = len(_event_buffers[run_id])
        logger.info(f"Event buffered ({buffer_size}): {event_type} for {run_id}")


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
