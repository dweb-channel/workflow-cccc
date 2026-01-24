from __future__ import annotations

import asyncio
from typing import Any, Callable, List, Optional, TypedDict

from langgraph.graph import END, StateGraph


class WorkflowState(TypedDict, total=False):
    request: str
    parsed_requirements: str
    assumptions: List[str]
    questions: List[str]
    plan: str
    review: str
    conflicts: List[str]
    foreman_summary: str
    tasks: List[str]
    initial_feedback: str
    final_feedback: str


def _peer1_plan(state: WorkflowState) -> WorkflowState:
    parsed = state.get("parsed_requirements", "")
    plan = (
        "Peer1 plan:\n"
        "1) Define workflow nodes and state schema.\n"
        "2) Add confirmation checkpoints and rollback paths.\n"
        "3) Implement Temporal workflow + worker.\n"
        "4) Add demo runner and docs.\n"
        f"Notes based on parsed requirements: {parsed}"
    )
    return {"plan": plan}


def _peer2_review(state: WorkflowState) -> WorkflowState:
    plan = state.get("plan", "")
    review = (
        "Peer2 review: Plan is coherent for MVP. "
        "No blocking issues; ensure confirmation checkpoints are explicit."
    )
    conflicts: List[str] = []
    if "confirmation" not in plan.lower():
        conflicts.append("Plan does not mention confirmation steps explicitly.")
    return {"review": review, "conflicts": conflicts}


def _foreman_summary(state: WorkflowState) -> WorkflowState:
    plan = state.get("plan", "")
    review = state.get("review", "")
    summary = "Foreman summary:\n" + plan + "\n\n" + review
    return {"foreman_summary": summary}


def _dispatch_tasks(state: WorkflowState) -> WorkflowState:
    tasks = [
        "Create LangGraph state + nodes",
        "Implement Temporal workflow with signals",
        "Run demo and capture output",
    ]
    return {"tasks": tasks}


def build_planning_graph():
    graph = StateGraph(WorkflowState)
    graph.add_node("peer1_plan", _peer1_plan)
    graph.add_node("peer2_review", _peer2_review)
    graph.add_node("foreman_summary", _foreman_summary)
    graph.add_node("dispatch_tasks", _dispatch_tasks)

    graph.set_entry_point("peer1_plan")
    graph.add_edge("peer1_plan", "peer2_review")
    graph.add_edge("peer2_review", "foreman_summary")
    graph.add_edge("foreman_summary", "dispatch_tasks")
    graph.add_edge("dispatch_tasks", END)

    return graph.compile()


def run_planning_graph(
    state: WorkflowState,
    on_node_event: Optional[Callable[[str, str, Any], None]] = None,
) -> WorkflowState:
    """Run the planning graph with optional event callback.

    Args:
        state: The initial workflow state
        on_node_event: Optional callback(node_name, status, output)
                       status is 'running' or 'completed'
    """
    graph = build_planning_graph()

    # If no callback, just run normally
    if on_node_event is None:
        return graph.invoke(state)

    # Run with streaming to capture node events
    result = state
    for event in graph.stream(state):
        # event is a dict like {'peer1_plan': {'plan': '...'}}
        for node_name, node_output in event.items():
            on_node_event(node_name, "completed", node_output)
            result = {**result, **node_output}

    return result


def get_graph_nodes() -> List[str]:
    """Return the list of node names in execution order."""
    return ["peer1_plan", "peer2_review", "foreman_summary", "dispatch_tasks"]
