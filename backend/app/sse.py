"""SSE Infrastructure — backward-compatible shim.

All logic has moved to app.event_bus.EventBus.
This module re-exports the old names so existing imports keep working.
New code should import from app.event_bus directly.
"""

from __future__ import annotations

from .event_bus import (
    get_event_bus,
    push_event,
    router,
    subscribe_events,
)

__all__ = [
    "push_node_event",
    "sse_event_generator",
    "router",
    "_active_streams",
]


def __getattr__(name: str):
    """Expose EventBus internals for test backward compat."""
    if name == "_active_streams":
        return get_event_bus()._streams
    if name == "_event_buffers":
        return get_event_bus()._buffers
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def push_node_event(run_id: str, event_type: str, data: dict) -> None:
    """Push an event — delegates to EventBus.push()."""
    push_event(run_id, event_type, data)


async def sse_event_generator(run_id: str):
    """Generate SSE events — delegates to EventBus.subscribe()."""
    async for event_str in subscribe_events(run_id):
        yield event_str
