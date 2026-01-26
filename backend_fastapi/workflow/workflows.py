from __future__ import annotations

from datetime import timedelta
from typing import Optional

from temporalio import workflow

with workflow.unsafe.imports_passed_through():
    from .activities import parse_requirements, plan_review_dispatch
    from .graph import WorkflowState
    from .config import TASK_QUEUE


@workflow.defn
class BusinessWorkflow:
    def __init__(self) -> None:
        self._state: WorkflowState = {}
        self._initial_decision: Optional[bool] = None
        self._initial_feedback: str = ""
        self._final_decision: Optional[bool] = None
        self._final_feedback: str = ""

    @workflow.run
    async def run(self, request: str) -> dict:
        # Include run_id for SSE event tracking
        run_id = workflow.info().workflow_id
        self._state = {"request": request, "run_id": run_id}

        self._state = await workflow.execute_activity(
            parse_requirements,
            self._state,
            schedule_to_close_timeout=timedelta(minutes=2),
        )

        await workflow.wait_condition(lambda: self._initial_decision is not None)
        if not self._initial_decision:
            return {
                "status": "rejected_at_initial_confirmation",
                "feedback": self._initial_feedback,
                "state": self._state,
            }

        self._state = {
            **self._state,
            "initial_feedback": self._initial_feedback,
        }

        self._state = await workflow.execute_activity(
            plan_review_dispatch,
            self._state,
            schedule_to_close_timeout=timedelta(minutes=10),
        )

        await workflow.wait_condition(lambda: self._final_decision is not None)
        if not self._final_decision:
            return {
                "status": "rejected_at_final_confirmation",
                "feedback": self._final_feedback,
                "state": self._state,
            }

        self._state = {
            **self._state,
            "final_feedback": self._final_feedback,
        }

        return {
            "status": "approved",
            "state": self._state,
        }

    @workflow.signal
    def confirm_initial(self, args: list) -> None:
        """Receive initial confirmation signal.

        Args:
            args: [approved: bool, feedback: str]
        """
        approved = args[0] if len(args) > 0 else False
        feedback = args[1] if len(args) > 1 else ""
        self._initial_decision = approved
        self._initial_feedback = feedback

    @workflow.signal
    def confirm_final(self, args: list) -> None:
        """Receive final confirmation signal.

        Args:
            args: [approved: bool, feedback: str]
        """
        approved = args[0] if len(args) > 0 else False
        feedback = args[1] if len(args) > 1 else ""
        self._final_decision = approved
        self._final_feedback = feedback

    @workflow.query
    def get_state(self) -> WorkflowState:
        return self._state

    @workflow.query
    def get_decisions(self) -> dict:
        return {
            "initial": self._initial_decision,
            "final": self._final_decision,
        }


__all__ = ["BusinessWorkflow", "TASK_QUEUE"]
