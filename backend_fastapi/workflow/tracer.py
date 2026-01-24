"""LangGraph node execution tracer for real-time status updates."""
from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any, AsyncGenerator, Dict, Optional

from langchain_core.callbacks import BaseCallbackHandler


class NodeTracer(BaseCallbackHandler):
    """Callback handler that traces LangGraph node execution.

    Captures node start/end events and pushes them to an async queue
    for SSE streaming.
    """

    def __init__(self, event_queue: asyncio.Queue):
        self.queue = event_queue
        self.current_node: Optional[str] = None

    def _now_iso(self) -> str:
        return datetime.utcnow().isoformat() + "Z"

    def on_chain_start(
        self,
        serialized: Dict[str, Any],
        inputs: Dict[str, Any],
        **kwargs: Any,
    ) -> None:
        """Called when a chain (node) starts."""
        node_name = serialized.get("name") or serialized.get("id", ["unknown"])[-1]
        self.current_node = node_name
        self.queue.put_nowait({
            "event": "node_update",
            "data": {
                "node": node_name,
                "status": "running",
                "timestamp": self._now_iso(),
            }
        })

    def on_chain_end(
        self,
        outputs: Dict[str, Any],
        **kwargs: Any,
    ) -> None:
        """Called when a chain (node) ends."""
        if self.current_node:
            self.queue.put_nowait({
                "event": "node_update",
                "data": {
                    "node": self.current_node,
                    "status": "completed",
                    "output": str(outputs)[:500],  # Truncate large outputs
                    "timestamp": self._now_iso(),
                }
            })
            self.current_node = None

    def on_chain_error(
        self,
        error: BaseException,
        **kwargs: Any,
    ) -> None:
        """Called when a chain (node) errors."""
        if self.current_node:
            self.queue.put_nowait({
                "event": "node_update",
                "data": {
                    "node": self.current_node,
                    "status": "failed",
                    "output": str(error)[:500],
                    "timestamp": self._now_iso(),
                }
            })
            self.current_node = None


async def stream_events(queue: asyncio.Queue) -> AsyncGenerator[str, None]:
    """Yield SSE formatted events from the queue."""
    while True:
        try:
            event = await asyncio.wait_for(queue.get(), timeout=30.0)
            if event is None:  # Sentinel to stop
                break
            import json
            yield f"event: {event['event']}\ndata: {json.dumps(event['data'])}\n\n"
        except asyncio.TimeoutError:
            # Send keepalive
            yield ": keepalive\n\n"
