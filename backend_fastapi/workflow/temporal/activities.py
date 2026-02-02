"""Temporal Activities for Dynamic Workflow Execution"""

from __future__ import annotations

import logging

from temporalio import activity

logger = logging.getLogger("workflow.activities")


@activity.defn
async def execute_dynamic_graph_activity(params: dict) -> dict:
    """Temporal activity that executes a dynamic workflow graph.

    Args:
        params: Dict with keys:
            - workflow_definition: Serialized WorkflowDefinition dict
            - initial_state: Initial state dict
            - run_id: Run ID for SSE tracking

    Returns:
        Final state dict from workflow execution
    """
    from ..engine.graph_builder import WorkflowDefinition, NodeConfig, EdgeDefinition
    from ..engine.executor import execute_dynamic_workflow

    # Ensure node types are registered
    import workflow.nodes.base  # noqa: F401
    import workflow.nodes.agents  # noqa: F401

    wf_dict = params.get("workflow_definition", {})
    initial_state = params.get("initial_state", {})
    run_id = params.get("run_id", "")

    # Reconstruct WorkflowDefinition from serialized dict
    nodes = [
        NodeConfig(id=n["id"], type=n["type"], config=n.get("config", {}))
        for n in wf_dict.get("nodes", [])
    ]
    edges = [
        EdgeDefinition(
            id=e["id"],
            source=e["source"],
            target=e["target"],
            condition=e.get("condition"),
        )
        for e in wf_dict.get("edges", [])
    ]

    workflow_def = WorkflowDefinition(
        name=wf_dict.get("name", "dynamic-workflow"),
        nodes=nodes,
        edges=edges,
        max_iterations=wf_dict.get("max_iterations", 10),
    )

    return await execute_dynamic_workflow(
        workflow_def=workflow_def,
        initial_state=initial_state,
        run_id=run_id,
    )
