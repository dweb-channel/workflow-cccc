"""Unified SSE Event Bus for real-time workflow updates.

Provides a single event bus that both batch bug-fix and design-to-spec
workflows use to push SSE events to connected clients.

Architecture:
  - In-process callers (design routes, spec_analyzer) use EventBus.push()
  - Cross-process callers (Temporal Worker) use HTTP POST to
    /api/internal/events/{job_id} which delegates to EventBus.push()
  - Clients subscribe via EventBus.subscribe() which returns an async generator

Event Envelope:
  {
    "event": "<event_type>",
    "data": {
      "job_id": "<job_id>",
      "timestamp": "<ISO 8601>",
      ...payload
    }
  }
"""

from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime, timezone
from typing import Any, AsyncGenerator, Dict, Optional

from fastapi import APIRouter
from pydantic import BaseModel

from workflow.logging_config import get_sse_logger

logger = get_sse_logger()

router = APIRouter()

# Buffer limits: prevent unbounded memory growth from orphaned jobs
BUFFER_MAX_EVENTS = 200
BUFFER_MAX_AGE_SECS = 600  # 10 minutes

# Stop signals: events that tell the SSE generator to close the connection
STOP_EVENTS = frozenset({"job_done", "workflow_complete"})


class EventBus:
    """Central event bus for SSE event management.

    Manages active SSE connections (queues), pre-connection event buffering,
    and provides push/subscribe interfaces for all workflow types.
    """

    def __init__(
        self,
        buffer_max_events: int = BUFFER_MAX_EVENTS,
        buffer_max_age_secs: int = BUFFER_MAX_AGE_SECS,
    ):
        self._streams: dict[str, asyncio.Queue] = {}
        self._buffers: dict[str, dict] = {}
        self._buffer_max_events = buffer_max_events
        self._buffer_max_age_secs = buffer_max_age_secs
        self._lock = asyncio.Lock()

    def push(self, job_id: str, event_type: str, data: dict) -> None:
        """Push an event to a connected client or buffer it.

        This is the single entry point for all SSE event publishing.
        Called directly by in-process code, or via the internal HTTP
        endpoint for cross-process callers (Temporal Worker).

        Note: This method is synchronous. In asyncio single-threaded context,
        dict reads/writes are atomic (no yield points), so the lock is not
        needed here. The lock protects subscribe/cleanup which have await points.

        Args:
            job_id: Job/run identifier
            event_type: Event type string (e.g. "bug_started", "spec_analyzed")
            data: Event payload dict (will be wrapped in envelope)
        """
        # Ensure timestamp in payload
        if "timestamp" not in data:
            data["timestamp"] = datetime.now(timezone.utc).isoformat()

        event = {"event": event_type, "data": data}
        queue = self._streams.get(job_id)
        if queue:
            queue.put_nowait(event)
            logger.info(f"Event sent: {event_type} for {job_id}")
        else:
            self._buffer_event(job_id, event, event_type)

    async def subscribe(
        self,
        job_id: str,
        stop_events: Optional[frozenset] = None,
        keepalive_interval: float = 30.0,
    ) -> AsyncGenerator[str, None]:
        """Subscribe to events for a job, yielding SSE-formatted strings.

        Creates a queue for this job_id, flushes any buffered events,
        then yields events as they arrive.

        Args:
            job_id: Job/run identifier to subscribe to
            stop_events: Event types that signal end of stream.
                         Defaults to STOP_EVENTS.
            keepalive_interval: Seconds between keepalive comments.

        Yields:
            SSE-formatted strings ("event: ...\ndata: ...\n\n")
        """
        if stop_events is None:
            stop_events = STOP_EVENTS

        logger.info(f"Client subscribed: {job_id}")
        queue: asyncio.Queue = asyncio.Queue()

        # Atomically register stream and flush buffered events
        async with self._lock:
            self._streams[job_id] = queue
            buf = self._buffers.pop(job_id, None)

        buffered = buf["events"] if buf else []
        if buffered:
            logger.info(
                f"Flushing {len(buffered)} buffered events for {job_id}"
            )
        for event in buffered:
            yield _format_sse(event)

        try:
            # Stream live events
            while True:
                try:
                    event = await asyncio.wait_for(
                        queue.get(), timeout=keepalive_interval
                    )
                    if event is None:  # Sentinel to stop
                        break
                    yield _format_sse(event)

                    if event.get("event") in stop_events:
                        break
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            async with self._lock:
                self._streams.pop(job_id, None)
                self._buffers.pop(job_id, None)

    def _buffer_event(
        self, job_id: str, event: dict, event_type: str
    ) -> None:
        """Buffer an event for a job that has no active subscriber yet."""
        if job_id not in self._buffers:
            self._cleanup_stale_buffers()
            self._buffers[job_id] = {
                "events": [],
                "created_at": time.monotonic(),
            }

        buf = self._buffers[job_id]
        if len(buf["events"]) < self._buffer_max_events:
            buf["events"].append(event)
            logger.info(
                f"Event buffered ({len(buf['events'])}): "
                f"{event_type} for {job_id}"
            )
        else:
            logger.warning(
                f"Buffer full ({self._buffer_max_events}), "
                f"dropping: {event_type} for {job_id}"
            )

    def _cleanup_stale_buffers(self) -> None:
        """Remove event buffers that are too old."""
        now = time.monotonic()
        stale = [
            rid
            for rid, buf in self._buffers.items()
            if now - buf["created_at"] > self._buffer_max_age_secs
        ]
        for rid in stale:
            removed = self._buffers.pop(rid, None)
            if removed:
                logger.info(
                    f"Cleaned up stale buffer for {rid} "
                    f"({len(removed['events'])} events)"
                )


def _format_sse(event: dict) -> str:
    """Format an event dict as an SSE string."""
    return f"event: {event['event']}\ndata: {json.dumps(event['data'])}\n\n"


# --- Singleton ---

_bus: Optional[EventBus] = None


def get_event_bus() -> EventBus:
    """Get the global EventBus singleton."""
    global _bus
    if _bus is None:
        _bus = EventBus()
    return _bus


# --- Convenience functions (drop-in replacements for app/sse.py) ---


def push_event(job_id: str, event_type: str, data: dict) -> None:
    """Push an SSE event (convenience wrapper around EventBus.push)."""
    get_event_bus().push(job_id, event_type, data)


async def subscribe_events(
    job_id: str,
    stop_events: Optional[frozenset] = None,
) -> AsyncGenerator[str, None]:
    """Subscribe to SSE events (convenience wrapper)."""
    async for event_str in get_event_bus().subscribe(
        job_id, stop_events=stop_events
    ):
        yield event_str


# --- Internal API for cross-process push (Temporal Worker → FastAPI) ---


class InternalEventRequest(BaseModel):
    event_type: str
    data: dict


@router.post("/api/internal/events/{run_id}")
async def push_event_endpoint(run_id: str, payload: InternalEventRequest):
    """Internal endpoint for cross-process SSE event push."""
    logger.info(f"Received event via API: {payload.event_type} for {run_id}")
    get_event_bus().push(run_id, payload.event_type, payload.data)
    return {"status": "ok", "run_id": run_id}
