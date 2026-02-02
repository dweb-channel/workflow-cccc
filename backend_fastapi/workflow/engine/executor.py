"""Dynamic Workflow Executor

Executes dynamically-built LangGraph workflows with SSE event notifications.
Bridges dynamic_graph.build_graph_from_config with the SSE push infrastructure.
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from datetime import datetime
from typing import Any, Dict, Optional

from .graph_builder import (
    WorkflowDefinition,
    build_graph_from_config,
    detect_loops,
)
from ..sse import notify_node_status, push_sse_event

logger = logging.getLogger(__name__)


class MaxIterationsExceeded(Exception):
    """Raised when a node exceeds the maximum iteration count."""

    def __init__(self, node_id: str, count: int, max_iterations: int):
        self.node_id = node_id
        self.count = count
        self.max_iterations = max_iterations
        super().__init__(
            f"Node '{node_id}' exceeded max iterations: {count}/{max_iterations}"
        )


async def execute_dynamic_workflow(
    workflow_def: WorkflowDefinition,
    initial_state: Dict[str, Any],
    run_id: str = "",
) -> Dict[str, Any]:
    """Execute a dynamic workflow definition with SSE event tracking.

    Compiles the workflow definition into a LangGraph, runs it via astream,
    and pushes SSE events for each node as it starts and completes.
    Tracks per-node execution counts and enforces max_iterations for loops.

    Args:
        workflow_def: The validated workflow definition
        initial_state: Initial state dict (user inputs, parameters)
        run_id: Run ID for SSE event tracking

    Returns:
        Final merged state dict with all node outputs
    """
    logger.info(
        f"Executing dynamic workflow '{workflow_def.name}' "
        f"with {len(workflow_def.nodes)} nodes, run_id={run_id}"
    )

    # Inject run_id into state for node-level SSE if needed
    state = {**initial_state, "run_id": run_id}

    # Detect if this workflow has loops
    loops = detect_loops(workflow_def)
    has_loops = len(loops) > 0
    loop_node_ids = set()
    for loop in loops:
        loop_node_ids.update(loop.cycle_path[:-1])

    if has_loops:
        logger.info(
            f"Workflow has {len(loops)} loop(s), "
            f"max_iterations={workflow_def.max_iterations}, "
            f"loop nodes: {loop_node_ids}"
        )

    # Push workflow-level start event
    if run_id:
        await push_sse_event(run_id, "workflow_start", {
            "workflow_name": workflow_def.name,
            "node_count": len(workflow_def.nodes),
            "has_loops": has_loops,
            "max_iterations": workflow_def.max_iterations,
            "timestamp": _now(),
        })

    # Build and compile the graph
    try:
        compiled_graph = build_graph_from_config(workflow_def)
    except (ValueError, ImportError) as e:
        logger.error(f"Failed to build graph: {e}")
        if run_id:
            await push_sse_event(run_id, "workflow_error", {
                "error": str(e),
                "timestamp": _now(),
            })
        return {"error": str(e), "success": False}

    # Per-node execution counter for loop control
    node_exec_count: Dict[str, int] = defaultdict(int)

    # Track which nodes have been notified as running
    notified_running = set()

    # Execute with streaming to capture per-node events
    try:
        # Notify all nodes as pending initially
        for node_config in workflow_def.nodes:
            if run_id:
                await notify_node_status(run_id, node_config.id, "pending")

        # Stream execution — LangGraph emits {node_id: output} per step
        async for event in compiled_graph.astream(state):
            for node_id, node_output in event.items():
                # Increment execution counter
                node_exec_count[node_id] += 1
                current_count = node_exec_count[node_id]

                # Check max_iterations for loop nodes
                if node_id in loop_node_ids and current_count > workflow_def.max_iterations:
                    raise MaxIterationsExceeded(
                        node_id, current_count, workflow_def.max_iterations
                    )

                # Emit loop_iteration SSE event for looping nodes
                if node_id in loop_node_ids and current_count > 1 and run_id:
                    await push_sse_event(run_id, "loop_iteration", {
                        "node_id": node_id,
                        "iteration": current_count,
                        "max_iterations": workflow_def.max_iterations,
                        "timestamp": _now(),
                    })

                # If we haven't notified running yet (first execution), do it now
                if node_id not in notified_running and run_id:
                    await notify_node_status(run_id, node_id, "running")
                    notified_running.add(node_id)

                # Merge into state
                state[node_id] = node_output

                # Notify completed with output
                if run_id:
                    output_str = (
                        node_output
                        if isinstance(node_output, str)
                        else json.dumps(node_output, ensure_ascii=False, default=str)
                    )
                    await notify_node_status(run_id, node_id, "completed", output_str)

                logger.info(
                    f"Node '{node_id}' completed "
                    f"(execution {current_count}"
                    f"{'/' + str(workflow_def.max_iterations) if node_id in loop_node_ids else ''}"
                    f")"
                )

    except MaxIterationsExceeded as e:
        logger.warning(f"Loop terminated: {e}")
        if run_id:
            await push_sse_event(run_id, "loop_terminated", {
                "node_id": e.node_id,
                "iteration": e.count,
                "max_iterations": e.max_iterations,
                "reason": "max_iterations_exceeded",
                "timestamp": _now(),
            })
        # Loop termination is not a hard error — return partial results
        state["loop_terminated"] = True
        state["loop_terminated_node"] = e.node_id
        state["loop_iterations"] = dict(node_exec_count)

    except Exception as e:
        logger.error(f"Workflow execution failed: {e}")
        if run_id:
            await push_sse_event(run_id, "workflow_error", {
                "error": str(e),
                "timestamp": _now(),
            })
        return {**state, "error": str(e), "success": False}

    # Push workflow-level completion event
    if run_id:
        await push_sse_event(run_id, "workflow_complete", {
            "timestamp": _now(),
            "node_count": len(workflow_def.nodes),
            "node_execution_counts": dict(node_exec_count),
        })

    state["success"] = True
    if node_exec_count:
        state["node_execution_counts"] = dict(node_exec_count)
    logger.info(f"Dynamic workflow '{workflow_def.name}' completed successfully")
    return state


def _now() -> str:
    return datetime.utcnow().isoformat() + "Z"
