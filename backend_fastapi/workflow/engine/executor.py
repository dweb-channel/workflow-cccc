"""Dynamic Workflow Executor

Executes dynamically-built LangGraph workflows with SSE event notifications.
Bridges dynamic_graph.build_graph_from_config with the SSE push infrastructure.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Dict, Optional

from .graph_builder import (
    WorkflowDefinition,
    build_graph_from_config,
)
from ..sse import notify_node_status, push_sse_event

logger = logging.getLogger(__name__)


async def execute_dynamic_workflow(
    workflow_def: WorkflowDefinition,
    initial_state: Dict[str, Any],
    run_id: str = "",
) -> Dict[str, Any]:
    """Execute a dynamic workflow definition with SSE event tracking.

    Compiles the workflow definition into a LangGraph, runs it via astream,
    and pushes SSE events for each node as it starts and completes.

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

    # Push workflow-level start event
    if run_id:
        await push_sse_event(run_id, "workflow_start", {
            "workflow_name": workflow_def.name,
            "node_count": len(workflow_def.nodes),
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
                # If we haven't notified running yet, do it now
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

                logger.info(f"Node '{node_id}' completed")

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
        })

    state["success"] = True
    logger.info(f"Dynamic workflow '{workflow_def.name}' completed successfully")
    return state


def _now() -> str:
    return datetime.utcnow().isoformat() + "Z"
