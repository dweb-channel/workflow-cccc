"""Temporal Workflow for Batch Bug Fix.

Orchestrates Claude CLI-based bug fixing with Temporal's
durability, timeout management, and cancellation support.
"""

from __future__ import annotations

from datetime import timedelta

from temporalio import workflow

with workflow.unsafe.imports_passed_through():
    from .batch_activities import execute_batch_bugfix_activity


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

        # Timeout: 15 min per bug (fix ~5min + verify ~3min + retries), min 30 min
        timeout_minutes = max(30, bug_count * 15)

        self._result = await workflow.execute_activity(
            execute_batch_bugfix_activity,
            params,
            schedule_to_close_timeout=timedelta(minutes=timeout_minutes),
            # Claude CLI nodes can take 5-10 min each; heartbeat is sent
            # periodically during execution (not just on node completion).
            heartbeat_timeout=timedelta(minutes=15),
        )

        return self._result

    @workflow.query
    def get_result(self) -> dict:
        """Query the current workflow result."""
        return self._result
