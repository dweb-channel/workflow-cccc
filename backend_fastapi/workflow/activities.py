from __future__ import annotations

from typing import List

from temporalio import activity

from .graph import WorkflowState, run_planning_graph


@activity.defn
async def parse_requirements(state: WorkflowState) -> WorkflowState:
    request = (state.get("request") or "").strip()
    parsed = f"Parsed requirement: {request}" if request else "Parsed requirement: (empty)"
    assumptions: List[str] = [
        "MVP focus; no production hardening yet.",
        "Human confirmation is required at two checkpoints.",
    ]
    questions: List[str] = [
        "Any compliance or audit logging requirements?",
        "Expected deployment environment (local, Docker, k8s)?",
    ]
    return {
        **state,
        "parsed_requirements": parsed,
        "assumptions": assumptions,
        "questions": questions,
    }


@activity.defn
async def plan_review_dispatch(state: WorkflowState) -> WorkflowState:
    return run_planning_graph(state)
