from __future__ import annotations

import asyncio
import json
from datetime import datetime
from typing import Any, Callable, List, Optional, TypedDict

import httpx
from langgraph.graph import END, StateGraph

from .claude_agent import run_claude_agent
from .logging_config import get_worker_logger

# API base URL for pushing SSE events
# Use 127.0.0.1 instead of localhost to avoid IPv6 timeout issues
API_BASE_URL = "http://127.0.0.1:8000"

logger = get_worker_logger()


class WorkflowState(TypedDict, total=False):
    request: str
    run_id: str  # Added for SSE event tracking
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


async def push_sse_event(run_id: str, event_type: str, data: dict) -> None:
    """Push SSE event to the API server.

    Args:
        run_id: The workflow run ID
        event_type: Event type (node_update, node_output, etc.)
        data: Event data payload
    """
    if not run_id:
        logger.warning(f"No run_id, skipping event: {event_type}")
        return

    url = f"{API_BASE_URL}/api/internal/events/{run_id}"
    payload = {"event_type": event_type, "data": data}
    logger.info(f"📤 Pushing event: {event_type} to {url}")

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(url, json=payload)
            logger.info(f"✅ Response: {resp.status_code}")
    except Exception as e:
        # Log error but don't fail workflow
        logger.error(f"❌ Failed to push event: {e}")


async def notify_node_status(run_id: str, node: str, status: str, output: Any = None) -> None:
    """Notify frontend about node status change.

    Args:
        run_id: The workflow run ID
        node: Node name
        status: Status (running, completed, error)
        output: Optional output data for completed status
    """
    timestamp = datetime.utcnow().isoformat() + "Z"

    # Push status update
    await push_sse_event(run_id, "node_update", {
        "node": node,
        "status": status,
        "timestamp": timestamp
    })

    # Push output if completed
    if status == "completed" and output is not None:
        await push_sse_event(run_id, "node_output", {
            "node": node,
            "output": output if isinstance(output, str) else json.dumps(output, ensure_ascii=False),
            "timestamp": timestamp
        })


PEER1_PLAN_PROMPT = """你是 Peer1，负责根据需求制定实施计划。

需求摘要：
{parsed_requirements}

假设条件：
{assumptions}

请制定详细的实施计划，包括：
1. 主要步骤
2. 技术方案
3. 风险点

输出计划内容（纯文本）："""

PEER2_REVIEW_PROMPT = """你是 Peer2，负责审核 Peer1 的计划。

Peer1 计划：
{plan}

请用自然语言 Markdown 格式输出审核结果：

## 🔍 计划审核

**审核意见：**
（对计划的整体评价，是否完整合理）

**发现的问题：**
- （列出计划中的问题或冲突，如果没有就写"暂无问题，计划可行"）

**改进建议：**
- （列出改进建议，如果没有就写"暂无"）

请直接输出 Markdown 内容。"""

FOREMAN_SUMMARY_PROMPT = """你是 Foreman，负责汇总团队的工作。

Peer1 计划：
{plan}

Peer2 审核：
{review}

冲突点：
{conflicts}

请汇总以上内容，生成最终执行摘要："""

DISPATCH_TASKS_PROMPT = """根据以下汇总，分解为具体的可执行任务。

汇总内容：
{foreman_summary}

请用自然语言 Markdown 格式输出任务列表：

## 📝 任务分发

**待执行任务：**
1. （任务描述）
2. （任务描述）
3. （任务描述）
...

**优先级说明：**
（简要说明任务的执行顺序或依赖关系）

请直接输出 Markdown 内容。"""


async def _peer1_plan(state: WorkflowState) -> WorkflowState:
    run_id = state.get("run_id", "")
    parsed = state.get("parsed_requirements", "")
    assumptions = state.get("assumptions", [])

    # Notify: running
    await notify_node_status(run_id, "peer1_plan", "running")

    prompt = PEER1_PLAN_PROMPT.format(
        parsed_requirements=parsed,
        assumptions="\n".join(f"- {a}" for a in assumptions) or "（无）",
    )
    plan = await run_claude_agent(prompt)

    # Notify: completed with output
    await notify_node_status(run_id, "peer1_plan", "completed", plan)

    return {"plan": plan}


async def _peer2_review(state: WorkflowState) -> WorkflowState:
    run_id = state.get("run_id", "")
    plan = state.get("plan", "")

    # Notify: running
    await notify_node_status(run_id, "peer2_review", "running")

    prompt = PEER2_REVIEW_PROMPT.format(plan=plan)
    result = await run_claude_agent(prompt)

    # Output is now human-readable Markdown
    output = {"review": result, "conflicts": []}

    # Notify: completed with Markdown output for display
    await notify_node_status(run_id, "peer2_review", "completed", result)

    return output


async def _foreman_summary(state: WorkflowState) -> WorkflowState:
    run_id = state.get("run_id", "")
    plan = state.get("plan", "")
    review = state.get("review", "")
    conflicts = state.get("conflicts", [])

    # Notify: running
    await notify_node_status(run_id, "foreman_summary", "running")

    prompt = FOREMAN_SUMMARY_PROMPT.format(
        plan=plan,
        review=review,
        conflicts="\n".join(f"- {c}" for c in conflicts) or "（无）",
    )
    summary = await run_claude_agent(prompt)

    # Notify: completed with output
    await notify_node_status(run_id, "foreman_summary", "completed", summary)

    return {"foreman_summary": summary}


async def _dispatch_tasks(state: WorkflowState) -> WorkflowState:
    run_id = state.get("run_id", "")
    foreman_summary = state.get("foreman_summary", "")

    # Notify: running
    await notify_node_status(run_id, "dispatch_tasks", "running")

    prompt = DISPATCH_TASKS_PROMPT.format(foreman_summary=foreman_summary)
    result = await run_claude_agent(prompt)

    # Output is now human-readable Markdown
    # Store the full markdown as the first "task" for state compatibility
    tasks = [result]

    # Notify: completed with Markdown output for display
    await notify_node_status(run_id, "dispatch_tasks", "completed", result)

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
    """Run the planning graph synchronously (for backward compatibility).

    For async execution, use run_planning_graph_async instead.
    """
    return asyncio.run(run_planning_graph_async(state, on_node_event))


async def run_planning_graph_async(
    state: WorkflowState,
    on_node_event: Optional[Callable[[str, str, Any], None]] = None,
) -> WorkflowState:
    """Run the planning graph asynchronously with optional event callback.

    Args:
        state: The initial workflow state
        on_node_event: Optional callback(node_name, status, output)
                       status is 'running' or 'completed'
    """
    graph = build_planning_graph()

    # If no callback, just run normally
    if on_node_event is None:
        return await graph.ainvoke(state)

    # Run with async streaming to capture node events
    result = state
    async for event in graph.astream(state):
        # event is a dict like {'peer1_plan': {'plan': '...'}}
        for node_name, node_output in event.items():
            on_node_event(node_name, "completed", node_output)
            result = {**result, **node_output}

    return result


def get_graph_nodes() -> List[str]:
    """Return the list of node names in execution order."""
    return ["peer1_plan", "peer2_review", "foreman_summary", "dispatch_tasks"]
