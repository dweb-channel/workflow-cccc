"""Agent Node Type Implementations

This module provides node types for LLM agent execution and verification.
These nodes enable dynamic workflows to invoke Claude CLI for AI-powered tasks.
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any, Dict, Optional

from ..agents.claude import run_claude_agent, stream_claude_events, ClaudeEvent
from .registry import BaseNodeImpl, register_node_type

logger = logging.getLogger(__name__)


def _transform_tool_use_event(event_dict: Dict[str, Any]) -> Dict[str, Any]:
    """Transform a tool_use event into a frontend-specific event type.

    Backend emits: {type: "tool_use", tool_name: "Read", content: "...", tool_input: {...}}
    Frontend expects: {type: "read", file: "...", lines: "..."} etc.
    """
    tool_name = event_dict.get("tool_name", "").lower()
    tool_input = event_dict.get("tool_input", {}) or {}

    if tool_name in ("read", "view"):
        return {
            "type": "read",
            "file": tool_input.get("file_path") or tool_input.get("path", ""),
            "lines": tool_input.get("lines") or tool_input.get("limit", ""),
            "description": tool_input.get("description", ""),
        }
    elif tool_name in ("edit", "write"):
        # Build diff preview from old_string/new_string if available
        diff_parts = []
        if tool_input.get("old_string"):
            diff_parts.append(f"- {tool_input['old_string'][:200]}")
        if tool_input.get("new_string"):
            diff_parts.append(f"+ {tool_input['new_string'][:200]}")
        return {
            "type": "edit",
            "file": tool_input.get("file_path") or tool_input.get("path", ""),
            "diff": "\n".join(diff_parts) if diff_parts else event_dict.get("content", ""),
        }
    elif tool_name in ("bash", "execute", "shell"):
        return {
            "type": "bash",
            "command": tool_input.get("command", ""),
            "output": "",  # Output comes later via tool_result
        }
    else:
        # Unknown tool — fall back to thinking-style display
        return {
            "type": "thinking",
            "content": f"[{event_dict.get('tool_name', 'Tool')}] {event_dict.get('content', '')}",
        }


def _make_sse_event_callback(inputs: Dict[str, Any], node_id: str):
    """Create a callback that pushes ClaudeEvents as SSE ai_thinking events.

    Uses job_id from inputs to route events to the correct SSE queue.
    Transforms tool_use events into frontend-specific types (read/edit/bash).
    Returns None if no job_id is available (non-batch context).
    """
    job_id = inputs.get("job_id")
    bug_index = inputs.get("current_index", 0)
    if not job_id:
        return None

    def on_event(event: ClaudeEvent):
        try:
            from app.routes.batch import push_job_event

            event_dict = event.to_dict()
            event_dict["node_id"] = node_id
            event_dict["bug_index"] = bug_index

            # Transform tool_use into specific frontend types
            if event.type == ClaudeEvent.TOOL_USE:
                transformed = _transform_tool_use_event(event_dict)
                transformed["timestamp"] = event_dict["timestamp"]
                transformed["node_id"] = node_id
                transformed["bug_index"] = bug_index
                push_job_event(job_id, "ai_thinking", transformed)
            else:
                push_job_event(job_id, "ai_thinking", event_dict)

            # Push stats on result events
            if event.type == ClaudeEvent.RESULT and event.usage:
                push_job_event(job_id, "ai_thinking_stats", {
                    "tokens_in": event.usage.get("input_tokens", 0),
                    "tokens_out": event.usage.get("output_tokens", 0),
                    "cost": event.cost_usd or 0,
                })
        except Exception:
            # Don't let SSE push failures break the workflow
            pass

    return on_event


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
        # Also render cwd in case it contains template variables
        cwd = _render_template(cwd, inputs)

        # Prepend system prompt if provided
        if system_prompt:
            full_prompt = f"{system_prompt}\n\n---\n\n{rendered_prompt}"
        else:
            full_prompt = rendered_prompt

        logger.info(f"LLMAgentNode {self.node_id}: Prompt length={len(full_prompt)}, cwd={cwd}, timeout={timeout}")

        # Create SSE callback for streaming AI thinking events
        on_event = _make_sse_event_callback(inputs, self.node_id)

        try:
            result = await stream_claude_events(
                full_prompt, cwd=cwd, timeout=timeout, on_event=on_event,
            )
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
    node_type="verify",
    display_name="Verify",
    description="Verifies fix results using Claude CLI or script execution",
    category="validation",
    input_schema={
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Node display name"},
            "verify_type": {
                "type": "string",
                "enum": ["llm_agent", "script", "claude"],
                "description": "Verification mode: llm_agent (Claude CLI) or script",
            },
            "prompt_template": {
                "type": "string",
                "description": "Prompt template for LLM verification (llm_agent mode)",
            },
            "system_prompt": {
                "type": "string",
                "description": "Optional system prompt for LLM verification (llm_agent mode)",
            },
            "cwd": {
                "type": "string",
                "description": "Working directory for Claude CLI (llm_agent mode)",
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
    """Node that verifies fix results using Claude CLI or script execution.

    Supports two verification modes:

    1. llm_agent (alias: claude): Invokes Claude CLI to independently verify the fix.
       Claude analyzes the fix and returns a verification result.

    2. script: Runs a local script (e.g., npm test, pytest) and checks
       the output against success/failure patterns.

    Example configs:

    llm_agent mode:
        {
            "verify_type": "llm_agent",
            "prompt_template": "验证 Bug {current_bug} 的修复是否正确",
            "cwd": "/path/to/project",
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

        verify_type = self.config.get("verify_type", "llm_agent")
        timeout_config = self.config.get("timeout")
        timeout = float(timeout_config) if timeout_config is not None else 300.0

        # "claude" is an alias for "llm_agent"
        if verify_type in ("llm_agent", "claude"):
            return await self._verify_with_llm(inputs, timeout)
        elif verify_type == "script":
            return await self._verify_with_script(inputs, timeout)
        else:
            logger.error(f"VerifyNode {self.node_id}: Unknown verify_type: {verify_type}")
            return {
                "verified": False,
                "message": f"Unknown verification type: {verify_type}",
                "details": {},
            }

    async def _verify_with_llm(
        self, inputs: Dict[str, Any], timeout: float
    ) -> Dict[str, Any]:
        """Verify using Claude CLI (direct subprocess call) with streaming."""
        prompt_template = self.config.get("prompt_template", "")
        system_prompt = self.config.get("system_prompt", "")
        cwd = self.config.get("cwd", ".")

        if not prompt_template:
            # Default verification prompt
            prompt_template = (
                "请验证以下 Bug 修复是否正确:\n\n"
                "Bug URL: {current_bug}\n"
                "修复结果: {fix_bug_peer.result}\n\n"
                "请检查修复是否完整，测试是否通过。"
                "回复 'VERIFIED' 表示验证通过，'FAILED' 表示验证失败，并说明原因。"
            )

        # Render the prompt template
        rendered_prompt = _render_template(prompt_template, inputs)
        # Also render cwd in case it contains template variables
        cwd = _render_template(cwd, inputs)

        # Prepend system prompt if provided
        if system_prompt:
            full_prompt = f"{system_prompt}\n\n---\n\n{rendered_prompt}"
        else:
            full_prompt = rendered_prompt

        logger.info(
            f"VerifyNode {self.node_id}: Verifying with Claude CLI, "
            f"prompt_len={len(full_prompt)}, cwd={cwd}, timeout={timeout}"
        )

        # Create SSE callback for streaming AI thinking events
        on_event = _make_sse_event_callback(inputs, self.node_id)

        try:
            response = await stream_claude_events(
                full_prompt, cwd=cwd, timeout=timeout, on_event=on_event,
            )

            if response.startswith("[Error]"):
                logger.error(f"VerifyNode {self.node_id}: Claude CLI error: {response[:200]}")
                return {
                    "verified": False,
                    "message": response[:500],
                    "details": {"error": "claude_cli_error", "full_response": response},
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
                "details": {"full_response": response},
            }

        except Exception as e:
            logger.error(f"VerifyNode {self.node_id}: LLM verification failed: {e}")
            return {
                "verified": False,
                "message": f"Verification error: {e}",
                "details": {"error": str(e)},
            }

    async def _verify_with_script(
        self, inputs: Dict[str, Any], timeout: float
    ) -> Dict[str, Any]:
        """Verify using a script execution."""
        import asyncio

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
                if re.search(success_pattern, combined_output, re.IGNORECASE):
                    verified = True
                else:
                    # If success_pattern is set but not found, consider it failed
                    verified = False

            if failure_pattern:
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
        if verify_type not in ["llm_agent", "claude", "script"]:
            errors.append({
                "field": "verify_type",
                "error": "Must be 'llm_agent', 'claude', or 'script'",
            })
            return errors

        if verify_type in ("llm_agent", "claude"):
            # prompt_template is optional (has default)
            pass

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
