"""Temporal Client Adapter

Manages Temporal client lifecycle and provides workflow start functions.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional
from uuid import uuid4

from temporalio.client import Client

from workflow.config import TASK_QUEUE as TEMPORAL_TASK_QUEUE, TEMPORAL_ADDRESS

logger = logging.getLogger(__name__)

# Singleton client instance (initialized via lifespan)
_client: Optional[Client] = None
_client_lock = asyncio.Lock()


async def init_temporal_client() -> Optional[Client]:
    """Initialize and return Temporal client singleton.

    Returns None if Temporal is not available (graceful degradation).
    """
    global _client
    async with _client_lock:
        if _client is None:
            try:
                _client = await Client.connect(TEMPORAL_ADDRESS)
                logger.info(f"Temporal 已连接: {TEMPORAL_ADDRESS}")
            except Exception as e:
                logger.warning(
                    f"Temporal 未连接 ({TEMPORAL_ADDRESS}): {e} — "
                    "工作流执行接口将返回 503，其他接口正常工作"
                )
                _client = None
    return _client


async def close_temporal_client() -> None:
    """Close Temporal client connection."""
    global _client
    if _client is not None:
        # Newer Temporal SDK versions don't require explicit close
        # Just release the reference
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


async def start_spec_pipeline(
    job_id: str,
    file_key: str,
    node_id: str,
    output_dir: str,
    model: str = "",
    component_count_estimate: int = 3,
) -> str:
    """Start a SpecPipelineWorkflow via Temporal and return the workflow ID.

    Args:
        job_id: Unique job identifier (e.g., spec_xxx)
        file_key: Figma file key
        node_id: Figma page node ID
        output_dir: Job output directory
        model: Claude model override
        component_count_estimate: Estimated component count for timeout calc

    Returns:
        Temporal workflow ID (spec-{job_id})
    """
    client = await get_client()
    workflow_id = f"spec-{job_id}"
    params = {
        "job_id": job_id,
        "file_key": file_key,
        "node_id": node_id,
        "output_dir": output_dir,
        "model": model,
        "component_count_estimate": component_count_estimate,
    }
    await client.start_workflow(
        "SpecPipelineWorkflow",
        params,
        id=workflow_id,
        task_queue=TEMPORAL_TASK_QUEUE,
    )
    return workflow_id
