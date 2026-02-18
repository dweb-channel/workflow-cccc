"""Temporal Workflow for Batch Bug Fix.

Orchestrates Claude CLI-based bug fixing with Temporal's
durability, timeout management, and cancellation support.
"""

from __future__ import annotations

from datetime import timedelta

from temporalio import workflow

with workflow.unsafe.imports_passed_through():
    from .batch_activities import execute_batch_bugfix_activity
    from ..settings import (
        BATCH_WORKFLOW_HEARTBEAT_TIMEOUT_MINUTES,
        BATCH_WORKFLOW_MIN_TIMEOUT_MINUTES,
        BATCH_WORKFLOW_PER_BUG_MINUTES,
    )


@workflow.defn
class BatchBugFixWorkflow:
    """Temporal workflow that executes batch bug fix via Claude CLI.

    Delegates to a single long-running activity that iterates through
    bugs sequentially (fix -> verify -> retry loop).
    """

    def __init__(self) -> None:
        self._result: dict = {}

    @workflow.run
    async def run(self, params: dict) -> dict:
        """Execute a batch bug fix workflow.

        Args:
            params: Dict with keys:
                - job_id: Unique job identifier
                - jira_urls: List of Jira bug URLs
                - cwd: Working directory for Claude CLI
                - config: Job configuration dict
        """
        bug_count = len(params.get("jira_urls", []))
        timeout_minutes = max(
            BATCH_WORKFLOW_MIN_TIMEOUT_MINUTES,
            bug_count * BATCH_WORKFLOW_PER_BUG_MINUTES,
        )

        self._result = await workflow.execute_activity(
            execute_batch_bugfix_activity,
            params,
            schedule_to_close_timeout=timedelta(minutes=timeout_minutes),
            heartbeat_timeout=timedelta(minutes=BATCH_WORKFLOW_HEARTBEAT_TIMEOUT_MINUTES),
        )

        return self._result

    @workflow.query
    def get_result(self) -> dict:
        """Query the current workflow result."""
        return self._result
