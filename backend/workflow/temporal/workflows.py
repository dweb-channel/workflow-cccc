"""Temporal Workflow Definitions"""

from __future__ import annotations

from datetime import timedelta

from temporalio import workflow

with workflow.unsafe.imports_passed_through():
    from .activities import execute_dynamic_graph_activity
    from ..config import TASK_QUEUE


@workflow.defn
class DynamicWorkflow:
    """Temporal workflow for executing user-defined dynamic graphs.

    Takes a serialized workflow definition and initial state,
    executes via LangGraph with SSE event tracking.
    """

    def __init__(self) -> None:
        self._result: dict = {}

    @workflow.run
    async def run(self, params: dict) -> dict:
        """Execute a dynamic workflow.

        Args:
            params: Dict with keys:
                - workflow_definition: Serialized workflow definition
                - initial_state: Initial input values
        """
        run_id = workflow.info().workflow_id

        # Inject run_id into params for the activity
        activity_params = {
            **params,
            "run_id": run_id,
        }

        # Timeout scales with node count (5 min per node, min 10 min)
        # For loops: multiply by max_iterations since nodes may execute multiple times
        wf_def = params.get("workflow_definition", {})
        node_count = len(wf_def.get("nodes", []))
        max_iterations = wf_def.get("max_iterations", 10)
        base_timeout = max(10, node_count * 5)
        # If max_iterations > 1 (loops may exist), scale timeout accordingly
        timeout_minutes = base_timeout * max(1, max_iterations // 5 + 1) if max_iterations > 1 else base_timeout

        self._result = await workflow.execute_activity(
            execute_dynamic_graph_activity,
            activity_params,
            schedule_to_close_timeout=timedelta(minutes=timeout_minutes),
        )

        return self._result

    @workflow.query
    def get_result(self) -> dict:
        return self._result


__all__ = ["DynamicWorkflow", "TASK_QUEUE"]
