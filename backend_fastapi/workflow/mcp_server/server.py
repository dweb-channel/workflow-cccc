"""
Workflow MCP Server - Tool definitions and handlers

Exposes workflow control tools for CCCC agents:
- workflow_run: Start a workflow execution
- workflow_status: Get workflow run status
- workflow_result: Get workflow execution result
- workflow_list: List available workflows
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional

# Import Temporal adapter for workflow execution
# Note: These imports will work when running from the backend_fastapi context
try:
    from ...app.temporal_adapter import (
        init_temporal_client,
        start_dynamic_workflow,
    )
    TEMPORAL_AVAILABLE = True
except ImportError:
    TEMPORAL_AVAILABLE = False


class MCPError(Exception):
    """MCP tool call error"""

    def __init__(self, code: str, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


# =============================================================================
# Tool Implementations
# =============================================================================


def workflow_run(request: str, workflow_definition: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Start a workflow execution with the given request.

    Args:
        request: The workflow request/requirement text
        workflow_definition: Optional workflow definition dict. If not provided,
            a default single-node workflow is used.

    Returns:
        run_id and status
    """
    if not TEMPORAL_AVAILABLE:
        raise MCPError(
            code="temporal_unavailable",
            message="Temporal client not available. Ensure backend is properly configured.",
        )

    if workflow_definition is None:
        workflow_definition = {
            "nodes": [{"id": "main", "type": "llm_agent", "config": {"prompt": request}}],
            "edges": [],
        }

    # Run async function in sync context
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    try:
        run_id = loop.run_until_complete(
            start_dynamic_workflow(workflow_definition, {"request": request})
        )
        return {
            "run_id": run_id,
            "status": "running",
            "message": f"Workflow started with request: {request[:100]}...",
        }
    except Exception as e:
        raise MCPError(
            code="workflow_start_failed",
            message=f"Failed to start workflow: {str(e)}",
        )


def workflow_status(run_id: str) -> Dict[str, Any]:
    """Get the status of a workflow run.

    Args:
        run_id: The workflow run ID

    Returns:
        Current status and metadata
    """
    if not run_id:
        raise MCPError(code="invalid_run_id", message="run_id is required")

    # TODO: Query Temporal for workflow status
    # For now, return a placeholder
    return {
        "run_id": run_id,
        "status": "unknown",
        "message": "Status query not yet implemented. Check Temporal UI for details.",
    }


def workflow_result(run_id: str) -> Dict[str, Any]:
    """Get the result of a completed workflow.

    Args:
        run_id: The workflow run ID

    Returns:
        Workflow result or error
    """
    if not run_id:
        raise MCPError(code="invalid_run_id", message="run_id is required")

    # TODO: Query Temporal for workflow result
    return {
        "run_id": run_id,
        "status": "unknown",
        "result": None,
        "message": "Result query not yet implemented. Check Temporal UI for details.",
    }


def workflow_list() -> Dict[str, Any]:
    """List available workflows.

    Returns:
        List of workflow definitions
    """
    # For now, we have one hardcoded workflow
    return {
        "workflows": [
            {
                "id": "business-workflow",
                "name": "Business Workflow",
                "description": "Multi-agent workflow with parse → plan → review → summarize → dispatch",
                "nodes": [
                    "parse_requirements",
                    "peer1_plan",
                    "peer2_review",
                    "foreman_summary",
                    "dispatch_tasks",
                ],
            }
        ],
        "total": 1,
    }


# =============================================================================
# MCP Tool Definitions
# =============================================================================


MCP_TOOLS: List[Dict[str, Any]] = [
    {
        "name": "workflow_run",
        "description": (
            "Start a workflow execution with a given request.\n\n"
            "The workflow follows a DAG pattern: parse_requirements → peer1_plan → peer2_review → foreman_summary → dispatch_tasks.\n"
            "Each node uses Claude CLI for AI-powered processing.\n\n"
            "Returns: run_id for tracking, initial status"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "request": {
                    "type": "string",
                    "description": "The workflow request or requirement text to process",
                },
            },
            "required": ["request"],
        },
    },
    {
        "name": "workflow_status",
        "description": (
            "Get the current status of a workflow run.\n\n"
            "Returns: status (pending/running/completed/failed), current node, progress"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "run_id": {
                    "type": "string",
                    "description": "The workflow run ID returned from workflow_run",
                },
            },
            "required": ["run_id"],
        },
    },
    {
        "name": "workflow_result",
        "description": (
            "Get the result of a completed workflow.\n\n"
            "Returns: final output, task list, any errors"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "run_id": {
                    "type": "string",
                    "description": "The workflow run ID returned from workflow_run",
                },
            },
            "required": ["run_id"],
        },
    },
    {
        "name": "workflow_list",
        "description": (
            "List available workflow definitions.\n\n"
            "Returns: list of workflows with their node structures"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
]


# =============================================================================
# Tool Call Handler
# =============================================================================


def handle_tool_call(name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
    """Handle MCP tool call by dispatching to the appropriate function."""

    if name == "workflow_run":
        request = str(arguments.get("request") or "").strip()
        if not request:
            raise MCPError(code="missing_request", message="request parameter is required")
        return workflow_run(request)

    if name == "workflow_status":
        run_id = str(arguments.get("run_id") or "").strip()
        return workflow_status(run_id)

    if name == "workflow_result":
        run_id = str(arguments.get("run_id") or "").strip()
        return workflow_result(run_id)

    if name == "workflow_list":
        return workflow_list()

    raise MCPError(
        code="unknown_tool",
        message=f"Unknown tool: {name}",
        details={"available_tools": [t["name"] for t in MCP_TOOLS]},
    )
