from __future__ import annotations

import os
from typing import Optional
from uuid import uuid4

from temporalio.client import Client

TEMPORAL_ADDRESS = os.getenv("TEMPORAL_ADDRESS", "localhost:7233")
TEMPORAL_TASK_QUEUE = os.getenv("TEMPORAL_TASK_QUEUE", "business-workflow-task-queue")

# Singleton client instance (initialized via lifespan)
_client: Optional[Client] = None


def resolve_workflow_name() -> str:
    try:
        from workflow.workflows import BusinessWorkflow
    except Exception as exc:  # pragma: no cover
        raise RuntimeError(
            "无法导入 workflow.workflows.BusinessWorkflow。"
        ) from exc
    return BusinessWorkflow.__name__


async def init_temporal_client() -> Optional[Client]:
    """Initialize and return Temporal client singleton.

    Returns None if Temporal is not available (graceful degradation).
    """
    global _client
    if _client is None:
        try:
            _client = await Client.connect(TEMPORAL_ADDRESS)
            print(f"✅ Temporal 已连接: {TEMPORAL_ADDRESS}")
        except Exception as e:
            print(f"⚠️ Temporal 未连接 ({TEMPORAL_ADDRESS}): {e}")
            print("   /run 和 /confirm 接口将返回 503，其他接口正常工作")
            _client = None
    return _client


async def close_temporal_client() -> None:
    """Close Temporal client connection."""
    global _client
    if _client is not None:
        await _client.service_client.close()
        _client = None


async def get_client() -> Client:
    """Get Temporal client, initializing if needed.

    Raises RuntimeError if Temporal is not connected.
    """
    global _client
    if _client is None:
        await init_temporal_client()
    if _client is None:
        raise RuntimeError("Temporal 未连接，请先启动 Temporal 服务")
    return _client


async def start_business_workflow(request_text: str) -> str:
    """Start a new BusinessWorkflow and return run ID."""
    workflow_type = resolve_workflow_name()
    client = await get_client()
    run = await client.start_workflow(
        workflow_type,
        request_text,
        id=f"wf-run-{uuid4()}",
        task_queue=TEMPORAL_TASK_QUEUE,
    )
    return run.id


async def send_confirm_signal(
    run_id: str, stage: str, approved: bool, feedback: str = ""
) -> None:
    """Send confirm signal to a running workflow.

    Args:
        run_id: The workflow run ID
        stage: Either "initial" or "final"
        approved: Whether the confirmation is approved
        feedback: Optional feedback message
    """
    client = await get_client()
    handle = client.get_workflow_handle(run_id)

    # Temporal signal() accepts a single arg; pack multiple params as a list
    signal_args = [approved, feedback]

    if stage == "initial":
        await handle.signal("confirm_initial", signal_args)
    elif stage == "final":
        await handle.signal("confirm_final", signal_args)
    else:
        raise ValueError(f"Invalid stage: {stage}. Must be 'initial' or 'final'.")
