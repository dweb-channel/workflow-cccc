"""Agent Node Type Implementations

This module provides node types for LLM agent execution and CCCC peer communication.
These nodes enable dynamic workflows to invoke Claude CLI and coordinate with CCCC peers.
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any, Dict, Optional

from ..agents.cccc import CCCCClient
from ..agents.claude import run_claude_agent
from .registry import BaseNodeImpl, register_node_type

logger = logging.getLogger(__name__)


def _render_template(template: str, context: Dict[str, Any]) -> str:
    """Render a prompt template with variable substitution.

    Supports two formats:
    - {variable_name} — simple top-level variable
    - {node_id.field_name} — nested field from upstream node output

    Args:
        template: Template string with {placeholders}
        context: Dictionary of available variables (flat or nested)

    Returns:
        Rendered string with placeholders replaced
    """
    def replacer(match: re.Match) -> str:
        key = match.group(1)
        # Try direct lookup first
        if key in context:
            val = context[key]
            return str(val) if not isinstance(val, str) else val

        # Try dotted path (e.g., "node_1.output")
        parts = key.split(".", 1)
        if len(parts) == 2:
            node_id, field = parts
            if node_id in context and isinstance(context[node_id], dict):
                val = context[node_id].get(field, "")
                return str(val) if not isinstance(val, str) else val

        # Leave unresolved placeholders as-is, but warn
        logger.warning(f"Unresolved template placeholder: {{{key}}}")
        return match.group(0)

    return re.sub(r"\{(\w+(?:\.\w+)?)\}", replacer, template)


@register_node_type(
    node_type="llm_agent",
    display_name="LLM Agent",
    description="Executes a prompt using Claude CLI and returns the result",
    category="agent",
    input_schema={
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Node display name"},
            "prompt": {"type": "string", "description": "Prompt template with {variable} placeholders"},
            "system_prompt": {"type": "string", "description": "Optional system-level instructions"},
            "cwd": {"type": "string", "description": "Working directory for Claude CLI"},
            "timeout": {"type": "number", "description": "Execution timeout in seconds (default 300)"},
        },
        "required": ["name", "prompt"],
    },
    output_schema={
        "type": "object",
        "properties": {
            "result": {"type": "string", "description": "Claude CLI output"},
            "success": {"type": "boolean"},
        },
    },
    icon="bot",
    color="#6366F1",
)
class LLMAgentNode(BaseNodeImpl):
    """Node that executes a prompt via Claude CLI.

    The prompt template supports variable substitution from upstream node outputs.
    For example: "Analyze this code: {data_source.code}"
    """

    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        logger.info(f"LLMAgentNode {self.node_id}: Executing")

        prompt_template = self.config.get("prompt", "")
        system_prompt = self.config.get("system_prompt", "")
        cwd = self.config.get("cwd", ".")
        timeout = float(self.config.get("timeout", 300))

        # Render the prompt template with upstream inputs
        rendered_prompt = _render_template(prompt_template, inputs)

        # Prepend system prompt if provided
        if system_prompt:
            full_prompt = f"{system_prompt}\n\n---\n\n{rendered_prompt}"
        else:
            full_prompt = rendered_prompt

        logger.info(f"LLMAgentNode {self.node_id}: Prompt length={len(full_prompt)}, cwd={cwd}, timeout={timeout}")

        try:
            result = await run_claude_agent(full_prompt, cwd=cwd, timeout=timeout)
            success = not result.startswith("[Error]")
            if not success:
                logger.error(f"LLMAgentNode {self.node_id}: Claude CLI error: {result[:200]}")
            return {"result": result, "success": success}
        except Exception as e:
            logger.error(f"LLMAgentNode {self.node_id}: Execution failed: {e}")
            return {"result": f"[Error] {e}", "success": False}

    def validate_config(self) -> list[Dict[str, str]]:
        errors = super().validate_config()
        prompt = self.config.get("prompt", "")
        if not prompt.strip():
            errors.append({"field": "prompt", "error": "Prompt template cannot be empty"})
        timeout = self.config.get("timeout")
        if timeout is not None:
            try:
                t = float(timeout)
                if t <= 0 or t > 3600:
                    errors.append({"field": "timeout", "error": "Timeout must be between 1 and 3600 seconds"})
            except (TypeError, ValueError):
                errors.append({"field": "timeout", "error": "Timeout must be a number"})
        return errors


@register_node_type(
    node_type="cccc_peer",
    display_name="CCCC Peer",
    description="Sends a prompt to a CCCC peer agent and waits for response",
    category="agent",
    input_schema={
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Node display name"},
            "peer_id": {"type": "string", "description": "Target CCCC peer actor ID (e.g., 'domain-expert')"},
            "prompt": {"type": "string", "description": "Message template with {variable} placeholders"},
            "command": {"type": "string", "description": "Optional command prefix (e.g., '/brainstorm')"},
            "group_id": {
                "type": "string",
                "description": "CCCC group ID (defaults to CCCC_GROUP_ID env var)",
            },
            "timeout": {"type": "number", "description": "Response wait timeout in seconds (default 120)"},
        },
        "required": ["name", "peer_id", "prompt"],
    },
    output_schema={
        "type": "object",
        "properties": {
            "response": {"type": "string", "description": "Peer's response text"},
            "success": {"type": "boolean"},
            "peer_id": {"type": "string"},
        },
    },
    icon="message-circle",
    color="#F59E0B",
)
class CCCCPeerNode(BaseNodeImpl):
    """Node that communicates with a CCCC peer agent.

    Sends a prompt to a specified CCCC peer and waits for their response.
    Uses the CCCCClient with a dedicated workflow-inbox for reliable polling.
    """

    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        logger.info(f"CCCCPeerNode {self.node_id}: Executing")

        peer_id = self.config.get("peer_id", "")
        prompt_template = self.config.get("prompt", "")
        command = self.config.get("command")
        group_id = self.config.get("group_id") or os.environ.get("CCCC_GROUP_ID", "")
        timeout = float(self.config.get("timeout", 120))

        if not group_id:
            logger.error(f"CCCCPeerNode {self.node_id}: No group_id configured and CCCC_GROUP_ID not set")
            return {
                "response": "[Error] No CCCC group_id configured",
                "success": False,
                "peer_id": peer_id,
            }

        # Render the prompt template with upstream inputs
        rendered_prompt = _render_template(prompt_template, inputs)

        logger.info(
            f"CCCCPeerNode {self.node_id}: Sending to peer={peer_id}, "
            f"command={command}, timeout={timeout}"
        )

        try:
            client = CCCCClient(group_id=group_id)
            response = await client.ask_peer(
                peer_id=peer_id,
                prompt=rendered_prompt,
                command=command,
                timeout=timeout,
            )

            if response is None:
                logger.warning(f"CCCCPeerNode {self.node_id}: Timeout waiting for {peer_id}")
                return {
                    "response": f"[Timeout] No response from {peer_id} within {timeout}s",
                    "success": False,
                    "peer_id": peer_id,
                }

            return {
                "response": response,
                "success": True,
                "peer_id": peer_id,
            }
        except Exception as e:
            logger.error(f"CCCCPeerNode {self.node_id}: Failed: {e}")
            return {
                "response": f"[Error] {e}",
                "success": False,
                "peer_id": peer_id,
            }

    def validate_config(self) -> list[Dict[str, str]]:
        errors = super().validate_config()
        peer_id = self.config.get("peer_id", "")
        if not peer_id.strip():
            errors.append({"field": "peer_id", "error": "Peer ID cannot be empty"})
        prompt = self.config.get("prompt", "")
        if not prompt.strip():
            errors.append({"field": "prompt", "error": "Prompt template cannot be empty"})
        timeout = self.config.get("timeout")
        if timeout is not None:
            try:
                t = float(timeout)
                if t <= 0 or t > 600:
                    errors.append({"field": "timeout", "error": "Timeout must be between 1 and 600 seconds"})
            except (TypeError, ValueError):
                errors.append({"field": "timeout", "error": "Timeout must be a number"})
        return errors
