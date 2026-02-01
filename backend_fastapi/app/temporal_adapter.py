"""Temporal Client Adapter

Manages Temporal client lifecycle and provides workflow start functions.
"""

from __future__ import annotations

import os
from typing import Optional
from uuid import uuid4

from temporalio.client import Client

from workflow.config import TASK_QUEUE as TEMPORAL_TASK_QUEUE

TEMPORAL_ADDRESS = os.getenv("TEMPORAL_ADDRESS", "localhost:7233")

# Singleton client instance (initialized via lifespan)
_client: Optional[Client] = None


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
            print("   工作流执行接口将返回 503，其他接口正常工作")
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


async def start_dynamic_workflow(
    workflow_definition: dict,
    initial_state: dict,
) -> str:
    """Start a DynamicWorkflow via Temporal and return run ID.

    Args:
        workflow_definition: Serialized WorkflowDefinition dict
        initial_state: Initial input values for the workflow

    Returns:
        Temporal workflow run ID
    """
    from workflow.temporal.workflows import DynamicWorkflow

    client = await get_client()
    params = {
        "workflow_definition": workflow_definition,
        "initial_state": initial_state,
    }
    run = await client.start_workflow(
        DynamicWorkflow.__name__,
        params,
        id=f"dyn-run-{uuid4()}",
        task_queue=TEMPORAL_TASK_QUEUE,
    )
    return run.id
