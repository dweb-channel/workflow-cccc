"""Workflow configuration.

This module provides configuration for workflow execution,
including executor settings for each node.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Dict, Literal, Optional


# Temporal task queue
TASK_QUEUE = "business-workflow-task-queue"


# Executor types
ExecutorType = Literal["claude_cli", "cccc_peer"]


@dataclass
class NodeConfig:
    """Configuration for a workflow node."""
    executor: ExecutorType = "claude_cli"
    peer_id: Optional[str] = None
    command: Optional[str] = None  # e.g., "/brainstorm", "/design"
    timeout: float = 120.0


@dataclass
class WorkflowConfig:
    """Configuration for the entire workflow."""

    # CCCC settings
    cccc_group_id: str = field(default_factory=lambda: os.environ.get("CCCC_GROUP_ID", "g_825b14153a07"))
    cccc_enabled: bool = field(default_factory=lambda: os.environ.get("CCCC_ENABLED", "false").lower() == "true")

    # Node configurations
    nodes: Dict[str, NodeConfig] = field(default_factory=dict)

    def __post_init__(self):
        # Default node configurations
        if not self.nodes:
            self.nodes = {
                "parse_requirements": NodeConfig(
                    executor="cccc_peer" if self.cccc_enabled else "claude_cli",
                    peer_id="superpowers-peer",
                    command="/brainstorm",
                    timeout=180.0,
                ),
                "peer1_plan": NodeConfig(
                    executor="claude_cli",
                    timeout=120.0,
                ),
                "peer2_review": NodeConfig(
                    executor="claude_cli",
                    timeout=120.0,
                ),
                "foreman_summary": NodeConfig(
                    executor="claude_cli",
                    timeout=60.0,
                ),
                "dispatch_tasks": NodeConfig(
                    executor="claude_cli",
                    timeout=60.0,
                ),
            }

    def get_node_config(self, node_name: str) -> NodeConfig:
        """Get configuration for a specific node."""
        return self.nodes.get(node_name, NodeConfig())


# Global configuration instance
_config: Optional[WorkflowConfig] = None


def get_config() -> WorkflowConfig:
    """Get the global workflow configuration."""
    global _config
    if _config is None:
        _config = WorkflowConfig()
    return _config


def set_config(config: WorkflowConfig) -> None:
    """Set the global workflow configuration."""
    global _config
    _config = config


def enable_cccc(group_id: Optional[str] = None) -> None:
    """Enable CCCC peer execution.

    Args:
        group_id: Optional CCCC group ID to use
    """
    global _config
    if _config is None:
        _config = WorkflowConfig()

    _config.cccc_enabled = True
    if group_id:
        _config.cccc_group_id = group_id

    # Update node configs to use CCCC
    _config.nodes["parse_requirements"] = NodeConfig(
        executor="cccc_peer",
        peer_id="superpowers-peer",
        command="/brainstorm",
        timeout=180.0,
    )


def disable_cccc() -> None:
    """Disable CCCC peer execution, use Claude CLI for all nodes."""
    global _config
    if _config is None:
        _config = WorkflowConfig()

    _config.cccc_enabled = False

    # Update node configs to use Claude CLI
    _config.nodes["parse_requirements"] = NodeConfig(
        executor="claude_cli",
        timeout=120.0,
    )
