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


# Jira MCP tool hint to prepend to prompts when enabled
JIRA_MCP_HINT = """
## 可用工具提示
如果需要获取 Jira Bug 详细信息，请使用 Jira MCP 工具：
- `mcp__jira__get_issue` - 获取 issue 详情（描述、状态、评论等）
- `mcp__jira__search` - JQL 搜索 issues
- `mcp__jira__get_comments` - 获取 issue 评论
- `mcp__jira__add_comment` - 添加评论到 issue
- `mcp__jira__update_issue` - 更新 issue 状态/字段

请在开始修复前先用 `mcp__jira__get_issue` 获取 Bug 完整信息。
---

"""


@register_node_type(
    node_type="cccc_peer",
    display_name="CCCC Peer",
    description="Sends a prompt to a CCCC peer agent via foreman coordination",
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
            "foreman_id": {
                "type": "string",
                "description": "Foreman actor ID for coordination (default: 'master')",
            },
            "via_foreman": {
                "type": "boolean",
                "description": "Route through foreman for coordination (default: true)",
            },
            "include_jira_hint": {
                "type": "boolean",
                "description": "Prepend Jira MCP tool usage hint to prompt (default: false)",
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
    """Node that communicates with a CCCC peer agent via foreman.

    Routes requests through the foreman (master) who coordinates peer execution.
    This integrates naturally with CCCC's multi-agent collaboration model.

    Architecture: Workflow → Foreman → Peer → Foreman → Workflow
    """

    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        logger.info(f"CCCCPeerNode {self.node_id}: Executing")

        # Render peer_id with template variables (e.g., "{fixer_peer_id}" -> actual peer id)
        peer_id_template = self.config.get("peer_id", "")
        peer_id = _render_template(peer_id_template, inputs)

        prompt_template = self.config.get("prompt", "")
        command = self.config.get("command")
        group_id = (
            self.config.get("group_id")
            or inputs.get("target_group_id")
            or os.environ.get("CCCC_GROUP_ID", "")
        )
        foreman_id = self.config.get("foreman_id", "master")
        via_foreman = self.config.get("via_foreman", True)
        # timeout: None means wait indefinitely (peer may take a long time)
        timeout_config = self.config.get("timeout")
        timeout = float(timeout_config) if timeout_config is not None else None

        if not group_id:
            logger.error(f"CCCCPeerNode {self.node_id}: No group_id configured and CCCC_GROUP_ID not set")
            return {
                "response": "[Error] No CCCC group_id configured",
                "success": False,
                "peer_id": peer_id,
            }

        # Render the prompt template with upstream inputs
        rendered_prompt = _render_template(prompt_template, inputs)

        # Prepend Jira MCP hint if enabled
        include_jira_hint = self.config.get("include_jira_hint", False)
        if include_jira_hint:
            rendered_prompt = JIRA_MCP_HINT + rendered_prompt
            logger.info(f"CCCCPeerNode {self.node_id}: Added Jira MCP hint to prompt")

        coordinator = foreman_id if via_foreman else peer_id
        timeout_str = f"{timeout}s" if timeout else "indefinite"
        logger.info(
            f"CCCCPeerNode {self.node_id}: Sending to {coordinator} "
            f"(peer={peer_id}, via_foreman={via_foreman}), timeout={timeout_str}"
        )

        try:
            # Support CCCC_MOCK environment variable for testing
            mock_mode = os.environ.get("CCCC_MOCK", "").lower() in ("true", "1", "yes")
            client = CCCCClient(group_id=group_id, foreman_id=foreman_id, mock=mock_mode)
            if mock_mode:
                logger.info(f"CCCCPeerNode {self.node_id}: Running in MOCK mode")
            response = await client.ask_peer(
                peer_id=peer_id,
                prompt=rendered_prompt,
                command=command,
                timeout=timeout,
                via_foreman=via_foreman,
            )

            if response is None:
                target = foreman_id if via_foreman else peer_id
                timeout_msg = f"within {timeout}s" if timeout else "(unexpected)"
                logger.warning(f"CCCCPeerNode {self.node_id}: No response from {target} {timeout_msg}")
                return {
                    "response": f"[No Response] No response from {target} {timeout_msg}",
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


@register_node_type(
    node_type="verify",
    display_name="Verify",
    description="Verifies fix results using CCCC peer or script execution",
    category="validation",
    input_schema={
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Node display name"},
            "verify_type": {
                "type": "string",
                "enum": ["cccc_peer", "script"],
                "description": "Verification mode: cccc_peer or script",
            },
            "peer_id": {
                "type": "string",
                "description": "CCCC peer ID for verification (cccc_peer mode)",
            },
            "prompt_template": {
                "type": "string",
                "description": "Prompt template for peer verification (cccc_peer mode)",
            },
            "command": {
                "type": "string",
                "description": "Script command to run (script mode)",
            },
            "working_dir": {
                "type": "string",
                "description": "Working directory for script (script mode)",
            },
            "success_pattern": {
                "type": "string",
                "description": "Regex pattern to match for success (script mode)",
            },
            "failure_pattern": {
                "type": "string",
                "description": "Regex pattern to match for failure (script mode)",
            },
            "timeout": {
                "type": "number",
                "description": "Execution timeout in seconds (default 300)",
            },
            "group_id": {
                "type": "string",
                "description": "CCCC group ID (defaults to CCCC_GROUP_ID env var)",
            },
        },
        "required": ["name", "verify_type"],
    },
    output_schema={
        "type": "object",
        "properties": {
            "verified": {"type": "boolean", "description": "Whether verification passed"},
            "message": {"type": "string", "description": "Verification result description"},
            "details": {"type": "object", "description": "Additional details"},
        },
    },
    icon="check-circle",
    color="#4CAF50",
)
class VerifyNode(BaseNodeImpl):
    """Node that verifies fix results using CCCC peer or script execution.

    Supports two verification modes:

    1. cccc_peer: Calls another CCCC peer to independently verify the fix.
       The peer analyzes the fix and returns a verification result.

    2. script: Runs a local script (e.g., npm test, pytest) and checks
       the output against success/failure patterns.

    Example configs:

    cccc_peer mode:
        {
            "verify_type": "cccc_peer",
            "peer_id": "verifier",
            "prompt_template": "验证 Bug {current_bug} 的修复是否正确",
            "timeout": 300
        }

    script mode:
        {
            "verify_type": "script",
            "command": "npm test",
            "working_dir": "/path/to/project",
            "success_pattern": "All tests passed",
            "timeout": 120
        }
    """

    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        logger.info(f"VerifyNode {self.node_id}: Executing")

        verify_type = self.config.get("verify_type", "cccc_peer")
        # timeout: None means wait indefinitely (peer may take a long time)
        timeout_config = self.config.get("timeout")
        timeout = float(timeout_config) if timeout_config is not None else None

        if verify_type == "cccc_peer":
            return await self._verify_with_peer(inputs, timeout)
        elif verify_type == "script":
            return await self._verify_with_script(inputs, timeout)
        else:
            logger.error(f"VerifyNode {self.node_id}: Unknown verify_type: {verify_type}")
            return {
                "verified": False,
                "message": f"Unknown verification type: {verify_type}",
                "details": {},
            }

    async def _verify_with_peer(
        self, inputs: Dict[str, Any], timeout: Optional[float]
    ) -> Dict[str, Any]:
        """Verify using a CCCC peer."""
        # Render peer_id with template variables (e.g., "{verifier_peer_id}" -> actual peer id)
        peer_id_template = self.config.get("peer_id", "verifier")
        peer_id = _render_template(peer_id_template, inputs)
        prompt_template = self.config.get("prompt_template", "")
        group_id = (
            self.config.get("group_id")
            or inputs.get("target_group_id")
            or os.environ.get("CCCC_GROUP_ID", "")
        )
        foreman_id = self.config.get("foreman_id", "master")
        via_foreman = self.config.get("via_foreman", False)

        if not group_id:
            logger.error(f"VerifyNode {self.node_id}: No CCCC group_id configured")
            return {
                "verified": False,
                "message": "No CCCC group_id configured",
                "details": {"error": "configuration_error"},
            }

        if not prompt_template:
            # Default verification prompt
            prompt_template = (
                "请验证以下 Bug 修复是否正确:\n\n"
                "Bug URL: {current_bug}\n"
                "修复结果: {fix_bug_peer.response}\n\n"
                "请检查修复是否完整，测试是否通过。"
                "回复 'VERIFIED' 表示验证通过，'FAILED' 表示验证失败，并说明原因。"
            )

        # Render the prompt template
        rendered_prompt = _render_template(prompt_template, inputs)

        logger.info(
            f"VerifyNode {self.node_id}: Verifying with peer '{peer_id}', timeout={timeout}"
        )

        try:
            mock_mode = os.environ.get("CCCC_MOCK", "").lower() in ("true", "1", "yes")
            client = CCCCClient(group_id=group_id, foreman_id=foreman_id, mock=mock_mode)

            if mock_mode:
                logger.info(f"VerifyNode {self.node_id}: Running in MOCK mode")

            response = await client.ask_peer(
                peer_id=peer_id,
                prompt=rendered_prompt,
                timeout=timeout,
                via_foreman=via_foreman,
            )

            if response is None:
                logger.warning(f"VerifyNode {self.node_id}: Timeout waiting for peer")
                return {
                    "verified": False,
                    "message": f"Timeout waiting for verification from {peer_id}",
                    "details": {"error": "timeout", "peer_id": peer_id},
                }

            # Parse verification result from response
            response_upper = response.upper()
            verified = "VERIFIED" in response_upper or "通过" in response

            # Also check for explicit failure indicators
            if "FAILED" in response_upper or "失败" in response or "未通过" in response:
                verified = False

            return {
                "verified": verified,
                "message": response[:500] if len(response) > 500 else response,
                "details": {"peer_id": peer_id, "full_response": response},
            }

        except Exception as e:
            logger.error(f"VerifyNode {self.node_id}: Peer verification failed: {e}")
            return {
                "verified": False,
                "message": f"Verification error: {e}",
                "details": {"error": str(e), "peer_id": peer_id},
            }

    async def _verify_with_script(
        self, inputs: Dict[str, Any], timeout: Optional[float]
    ) -> Dict[str, Any]:
        """Verify using a script execution."""
        import asyncio
        import subprocess

        command = self.config.get("command", "")
        working_dir = self.config.get("working_dir", ".")
        success_pattern = self.config.get("success_pattern", "")
        failure_pattern = self.config.get("failure_pattern", "")

        if not command:
            return {
                "verified": False,
                "message": "No command specified for script verification",
                "details": {"error": "configuration_error"},
            }

        # Render template variables in command and working_dir
        rendered_command = _render_template(command, inputs)
        rendered_working_dir = _render_template(working_dir, inputs)

        logger.info(
            f"VerifyNode {self.node_id}: Running script '{rendered_command}' "
            f"in '{rendered_working_dir}', timeout={timeout}"
        )

        try:
            # Run the script asynchronously
            process = await asyncio.create_subprocess_shell(
                rendered_command,
                cwd=rendered_working_dir,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(), timeout=timeout
                )
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
                return {
                    "verified": False,
                    "message": f"Script timed out after {timeout}s",
                    "details": {"error": "timeout", "command": rendered_command},
                }

            stdout_text = stdout.decode("utf-8", errors="replace")
            stderr_text = stderr.decode("utf-8", errors="replace")
            combined_output = stdout_text + "\n" + stderr_text
            exit_code = process.returncode

            logger.info(
                f"VerifyNode {self.node_id}: Script exited with code {exit_code}"
            )

            # Determine verification result
            verified = exit_code == 0

            # Check patterns if provided
            if success_pattern:
                import re
                if re.search(success_pattern, combined_output, re.IGNORECASE):
                    verified = True
                else:
                    # If success_pattern is set but not found, consider it failed
                    verified = False

            if failure_pattern:
                import re
                if re.search(failure_pattern, combined_output, re.IGNORECASE):
                    verified = False

            # Truncate output for message
            output_preview = combined_output[:500]
            if len(combined_output) > 500:
                output_preview += "... (truncated)"

            return {
                "verified": verified,
                "message": f"Exit code: {exit_code}. {output_preview}",
                "details": {
                    "exit_code": exit_code,
                    "stdout": stdout_text[:2000],
                    "stderr": stderr_text[:2000],
                    "command": rendered_command,
                },
            }

        except Exception as e:
            logger.error(f"VerifyNode {self.node_id}: Script execution failed: {e}")
            return {
                "verified": False,
                "message": f"Script execution error: {e}",
                "details": {"error": str(e), "command": rendered_command},
            }

    def validate_config(self) -> list[Dict[str, str]]:
        errors = super().validate_config()

        verify_type = self.config.get("verify_type", "")
        if verify_type not in ["cccc_peer", "script"]:
            errors.append({
                "field": "verify_type",
                "error": "Must be 'cccc_peer' or 'script'",
            })
            return errors

        if verify_type == "cccc_peer":
            peer_id = self.config.get("peer_id", "")
            if not peer_id.strip():
                errors.append({"field": "peer_id", "error": "Peer ID required for cccc_peer mode"})

        elif verify_type == "script":
            command = self.config.get("command", "")
            if not command.strip():
                errors.append({"field": "command", "error": "Command required for script mode"})

        timeout = self.config.get("timeout")
        if timeout is not None:
            try:
                t = float(timeout)
                if t <= 0 or t > 3600:
                    errors.append({
                        "field": "timeout",
                        "error": "Timeout must be between 1 and 3600 seconds",
                    })
            except (TypeError, ValueError):
                errors.append({"field": "timeout", "error": "Timeout must be a number"})

        return errors
