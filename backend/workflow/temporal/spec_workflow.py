"""Temporal Workflow for Design-to-Spec Pipeline.

Orchestrates Figma → FrameDecomposer → SpecAnalyzer → SpecAssembler
with Temporal's durability, timeout management, and cancellation support.
"""

from __future__ import annotations

from datetime import timedelta

from temporalio import workflow

with workflow.unsafe.imports_passed_through():
    from .spec_activities import execute_spec_pipeline_activity
    from ..settings import (
        SPEC_WORKFLOW_HEARTBEAT_TIMEOUT_MINUTES,
        SPEC_WORKFLOW_MIN_TIMEOUT_MINUTES,
        SPEC_WORKFLOW_OVERHEAD_MINUTES,
        SPEC_WORKFLOW_PER_COMPONENT_MINUTES,
    )


@workflow.defn
class SpecPipelineWorkflow:
    """Temporal workflow that executes the design-to-spec pipeline.

    Delegates to a single long-running activity that runs all 4 phases:
      1. Figma data fetch (node tree + screenshots + tokens)
      2. FrameDecomposer — structural extraction (70%)
      3. SpecAnalyzer — LLM vision analysis (30%)
      4. SpecAssembler — final spec assembly + validation
    """

    def __init__(self) -> None:
        self._result: dict = {}

    @workflow.run
    async def run(self, params: dict) -> dict:
        """Execute a design-to-spec pipeline.

        Args:
            params: Dict with keys:
                - job_id: Unique job identifier (e.g., spec_xxx)
                - file_key: Figma file key
                - node_id: Figma page node ID
                - output_dir: Job output directory
                - model: Claude model override (optional)
        """
        component_count = params.get("component_count_estimate", 3)
        timeout_minutes = max(
            SPEC_WORKFLOW_MIN_TIMEOUT_MINUTES,
            component_count * SPEC_WORKFLOW_PER_COMPONENT_MINUTES
            + SPEC_WORKFLOW_OVERHEAD_MINUTES,
        )

        self._result = await workflow.execute_activity(
            execute_spec_pipeline_activity,
            params,
            schedule_to_close_timeout=timedelta(minutes=timeout_minutes),
            heartbeat_timeout=timedelta(minutes=SPEC_WORKFLOW_HEARTBEAT_TIMEOUT_MINUTES),
        )

        return self._result

    @workflow.query
    def get_result(self) -> dict:
        """Query the current workflow result."""
        return self._result
