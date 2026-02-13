"""Agent Node Type Implementations

This module provides node types for LLM agent execution and verification.
These nodes enable dynamic workflows to invoke Claude CLI for AI-powered tasks.
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any, Callable, Dict, Optional

from ..agents.claude import run_claude_agent, stream_claude_events, ClaudeEvent
from .registry import BaseNodeImpl, register_node_type

logger = logging.getLogger(__name__)


# --- Configurable Event Push ---
# Temporal worker sets this via set_job_event_pusher() to an HTTP-based pusher.
_job_event_push_fn: Optional[Callable] = None


def set_job_event_pusher(fn: Callable[[str, str, Dict[str, Any]], None]) -> None:
    """Configure the function used to push batch job SSE events.

    Args:
        fn: Callable(job_id, event_type, data) — pushes one event.
    """
    global _job_event_push_fn
    _job_event_push_fn = fn


def _humanize_tool_event(event_dict: Dict[str, Any]) -> Dict[str, Any]:
    """Transform a tool_use event into a human-readable, Chinese-friendly format.

    Produces conversational descriptions like Claude terminal output style.
    """
    tool_name = event_dict.get("tool_name", "").lower()
    tool_input = event_dict.get("tool_input", {}) or {}

    if tool_name in ("read", "view"):
        file_path = tool_input.get("file_path") or tool_input.get("path", "")
        # Extract short filename for display
        short_name = file_path.rsplit("/", 1)[-1] if "/" in file_path else file_path
        lines_info = ""
        if tool_input.get("offset") or tool_input.get("limit"):
            lines_info = f"（第 {tool_input.get('offset', 1)} 行起）"
        return {
            "type": "read",
            "file": file_path,
            "lines": lines_info,
            "description": f"正在读取 {short_name} 的内容，了解代码结构...",
        }
    elif tool_name in ("edit", "write"):
        file_path = tool_input.get("file_path") or tool_input.get("path", "")
        short_name = file_path.rsplit("/", 1)[-1] if "/" in file_path else file_path
        diff_parts = []
        if tool_input.get("old_string"):
            diff_parts.append(f"- {tool_input['old_string'][:200]}")
        if tool_input.get("new_string"):
            diff_parts.append(f"+ {tool_input['new_string'][:200]}")
        diff_text = "\n".join(diff_parts) if diff_parts else ""
        description = f"正在修改 {short_name}"
        if tool_name == "write":
            description = f"正在创建文件 {short_name}"
        return {
            "type": "edit",
            "file": file_path,
            "diff": diff_text or event_dict.get("content", ""),
            "description": description,
        }
    elif tool_name in ("bash", "execute", "shell"):
        command = tool_input.get("command", "")
        # Generate human-friendly description based on command
        desc = tool_input.get("description", "")
        if not desc:
            if "test" in command or "pytest" in command:
                desc = "正在运行测试，验证修改是否正确..."
            elif "git" in command:
                desc = "正在执行 Git 操作..."
            elif "npm" in command or "yarn" in command:
                desc = "正在执行前端构建/安装..."
            elif "grep" in command or "find" in command:
                desc = "正在搜索相关代码..."
            elif "ls" in command:
                desc = "正在查看目录结构..."
            elif "cat" in command or "head" in command:
                desc = "正在查看文件内容..."
            else:
                desc = "正在执行命令..."
        return {
            "type": "bash",
            "command": command,
            "output": "",
            "description": desc,
        }
    elif tool_name in ("glob", "grep", "search"):
        pattern = tool_input.get("pattern", "")
        return {
            "type": "thinking",
            "content": f"🔍 正在搜索代码：{pattern}",
        }
    elif tool_name in ("webfetch", "web_fetch"):
        url = tool_input.get("url", "")
        return {
            "type": "thinking",
            "content": f"🌐 正在访问网页获取信息：{url[:80]}...",
        }
    elif tool_name in ("task",):
        desc = tool_input.get("description", "")
        return {
            "type": "thinking",
            "content": f"📋 正在执行子任务：{desc}" if desc else "📋 正在执行子任务...",
        }
    else:
        # Unknown tool — show with Chinese description
        original_name = event_dict.get("tool_name", "Tool")
        content = event_dict.get("content", "")
        if len(content) > 200:
            content = content[:200] + "..."
        return {
            "type": "thinking",
            "content": f"🔧 正在使用工具 {original_name}：{content}" if content else f"🔧 正在使用工具 {original_name}",
        }


def _make_sse_event_callback(inputs: Dict[str, Any], node_id: str):
    """Create a callback that pushes ClaudeEvents as SSE ai_thinking events.

    Uses job_id from inputs to route events to the correct SSE queue.
    Filters noisy exploration events (read/glob/grep) to keep output clean.
    Only pushes key events: thinking, edit/write, bash, and final results.
    Returns None if no job_id is available or no push function is configured.
    """
    job_id = inputs.get("job_id")
    bug_index = inputs.get("current_index", 0)
    if not job_id:
        return None

    # Use configured pusher (set by batch_activities via set_job_event_pusher)
    push_fn = _job_event_push_fn
    if push_fn is None:
        return None

    # Node ID -> Chinese label for frontend display
    _NODE_LABEL_MAP: Dict[str, str] = {
        "get_current_bug": "获取 Bug 信息",
        "fix_bug_peer": "修复 Bug",
        "verify_fix": "验证修复结果",
        "increment_retry": "准备重试",
        "update_success": "修复完成",
        "update_failure": "修复失败",
    }
    node_label = _NODE_LABEL_MAP.get(node_id, node_id)

    # Whitelist: only these tools are shown in the AI thinking panel
    _IMPORTANT_TOOLS = frozenset({
        "edit", "write", "bash", "execute", "shell",
    })

    # Counter for suppressed exploration events (used for periodic summary)
    state = {"explore_count": 0, "last_explore_summary_at": 0}

    def on_event(event: ClaudeEvent):
        try:
            import time

            event_dict = event.to_dict()
            event_dict["node_id"] = node_id
            event_dict["node_label"] = node_label
            event_dict["bug_index"] = bug_index

            if event.type == ClaudeEvent.TOOL_USE:
                tool_name = (event.tool_name or "").lower()

                # Whitelist: only show code-change tools (edit/write/bash)
                if tool_name in _IMPORTANT_TOOLS:
                    transformed = _humanize_tool_event(event_dict)
                    transformed["timestamp"] = event_dict["timestamp"]
                    transformed["node_id"] = node_id
                    transformed["node_label"] = node_label
                    transformed["bug_index"] = bug_index
                    push_fn(job_id, "ai_thinking", transformed)
                else:
                    # All other tools (read, grep, MCP, TodoWrite, etc.) — suppress
                    state["explore_count"] += 1
                    now = time.monotonic()
                    if (state["explore_count"] % 20 == 1
                            or now - state["last_explore_summary_at"] > 30):
                        state["last_explore_summary_at"] = now
                        push_fn(job_id, "ai_thinking", {
                            "type": "thinking",
                            "content": f"正在分析代码... (已探索 {state['explore_count']} 个文件/位置)",
                            "timestamp": event_dict["timestamp"],
                            "node_id": node_id,
                            "node_label": node_label,
                            "bug_index": bug_index,
                        })
                return

            elif event.type == ClaudeEvent.TEXT:
                # Skip all intermediate text output (usually English Claude output)
                # Only the RESULT event matters for final output
                return

            elif event.type == ClaudeEvent.RESULT:
                # Final result — node-aware Chinese labels
                content = event.content
                if event.is_error:
                    event_dict["content"] = f"执行出错：{content}"
                else:
                    # Truncate long results to keep panel clean
                    if len(content) > 800:
                        content = content[:800] + "\n..."
                    event_dict["content"] = content
                # Include exploration summary in result
                if state["explore_count"] > 0:
                    event_dict["explore_count"] = state["explore_count"]
                push_fn(job_id, "ai_thinking", event_dict)

            else:
                # THINKING events — skip to reduce noise
                # User only needs to see actions (edit/bash) and results
                return

            # Push stats on result events
            if event.type == ClaudeEvent.RESULT and event.usage:
                push_fn(job_id, "ai_thinking_stats", {
                    "tokens_in": event.usage.get("input_tokens", 0),
                    "tokens_out": event.usage.get("output_tokens", 0),
                    "cost": event.cost_usd or 0,
                })
        except Exception:
            # Don't let SSE push failures break the workflow
            pass

    return on_event


def _extract_fix_summary(result: str, max_len: int = 500) -> str:
    """Extract a concise summary from fix node output.

    Tries to parse the structured format (根因分析 + 修改摘要 + 测试结果).
    Falls back to truncated raw output.
    """
    sections = []
    for header in ("## 根因分析", "## 修改摘要", "## 测试结果"):
        idx = result.find(header)
        if idx >= 0:
            # Find the end (next ## or end of string)
            end = result.find("\n## ", idx + len(header))
            section = result[idx:end].strip() if end > 0 else result[idx:].strip()
            sections.append(section)

    if sections:
        summary = "\n".join(sections)
        return summary[:max_len] + ("..." if len(summary) > max_len else "")

    # Fallback: truncate raw output
    return result[:max_len] + ("..." if len(result) > max_len else "")


def _accumulate_fix_context(
    inputs: Dict[str, Any], result: str, success: bool,
) -> Dict[str, Any]:
    """Build updated context after a fix node execution.

    Writes fix_summary, fix_attempt_N, and retry_history.
    Only called when 'context' field exists in workflow state.
    """
    ctx = dict(inputs.get("context") or {})
    attempt = int(inputs.get("retry_count", 0)) + 1

    summary = _extract_fix_summary(result)
    ctx["fix_summary"] = summary
    ctx[f"fix_attempt_{attempt}"] = summary[:300]

    # Build retry_history as a readable string for prompt injection
    history_parts = []
    for i in range(1, attempt + 1):
        key = f"fix_attempt_{i}"
        if key in ctx:
            history_parts.append(f"尝试 {i}: {ctx[key][:200]}")
    ctx["retry_history"] = "\n".join(history_parts) if history_parts else "首次尝试"

    return ctx


def _accumulate_verify_context(
    inputs: Dict[str, Any], verified: bool, message: str,
) -> Dict[str, Any]:
    """Build updated context after a verify node execution.

    Writes verify_feedback, verify_result, and updates retry_history.
    Only called when 'context' field exists in workflow state.
    """
    ctx = dict(inputs.get("context") or {})
    attempt = int(inputs.get("retry_count", 0)) + 1

    ctx["verify_feedback"] = message[:300]
    ctx["verify_result"] = "VERIFIED" if verified else "FAILED"

    # Update retry_history with verify result appended
    history_parts = []
    for i in range(1, attempt + 1):
        fix_key = f"fix_attempt_{i}"
        fix_text = ctx.get(fix_key, "")[:150]
        if fix_text:
            if i == attempt:
                verify_label = "通过" if verified else "失败"
                history_parts.append(f"尝试 {i}: 修复={fix_text} → 验证={verify_label}")
            else:
                history_parts.append(f"尝试 {i}: 修复={fix_text} → 验证=失败")
    ctx["retry_history"] = "\n".join(history_parts) if history_parts else ""

    return ctx


def _parse_verify_verdict(response: str) -> bool:
    """Parse verification verdict from Claude's response.

    Uses a priority-based approach:
    1. Structured verdict line (e.g., "VERDICT: VERIFIED", "结论: 通过")
    2. Word-boundary keyword matching (avoids "UNVERIFIED" matching "VERIFIED")
    3. Explicit failure always wins over implicit pass

    Returns True if verified, False otherwise.
    """
    response_upper = response.upper()

    # --- Priority 1: Structured verdict lines ---
    # Match patterns like "VERDICT: VERIFIED", "## 结论: 通过", "Result: FAILED"
    verdict_patterns = [
        r"(?:VERDICT|RESULT|CONCLUSION)\s*[:：]\s*(VERIFIED|PASSED|FAILED|REJECTED)",
        r"(?:结论|结果|判定)\s*[:：]\s*(通过|验证通过|失败|未通过|验证失败)",
    ]
    for pattern in verdict_patterns:
        m = re.search(pattern, response, re.IGNORECASE)
        if m:
            verdict = m.group(1).upper()
            if verdict in ("VERIFIED", "PASSED"):
                return True
            if verdict in ("FAILED", "REJECTED"):
                return False
            # Chinese verdicts
            verdict_raw = m.group(1)
            if verdict_raw in ("通过", "验证通过"):
                return True
            if verdict_raw in ("失败", "未通过", "验证失败"):
                return False

    # --- Priority 2: Word-boundary keyword matching ---
    # Use \b to avoid "UNVERIFIED" matching "VERIFIED"
    has_verified = bool(re.search(r"\bVERIFIED\b", response_upper))
    has_passed = "通过" in response and "未通过" not in response

    has_failed = bool(re.search(r"\bFAILED\b", response_upper))
    has_cn_failed = "失败" in response or "未通过" in response

    # Explicit failure always wins
    if has_failed or has_cn_failed:
        return False

    if has_verified or has_passed:
        return True

    # Default: ambiguous response treated as failure (safe default)
    return False


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
            # Detect structured failure indicators in the summary sections
            # (e.g., agent couldn't access Jira URL or produced no modifications).
            # Only check within ## 根因分析 and ## 修改摘要 sections to avoid
            # false positives from legitimate content like "修改了不可达的代码路径".
            if success:
                _FAILURE_INDICATORS = (
                    # Chinese
                    "无修改", "无法获取", "不可达", "无法访问",
                    # English
                    "no modifications", "no changes made", "unable to fetch",
                    "unreachable", "unable to access", "inaccessible",
                    "could not access", "failed to retrieve", "no fix applied",
                )
                summary_text = _extract_fix_summary(result, max_len=1000)
                if summary_text:
                    summary_lower = summary_text.lower()
                    matched = any(
                        ind in (summary_text if not ind.isascii() else summary_lower)
                        for ind in _FAILURE_INDICATORS
                    )
                    if matched:
                        success = False
                        logger.warning(
                            f"LLMAgentNode {self.node_id}: Summary contains failure indicator: {summary_text[:200]}"
                        )
            if not success:
                logger.error(f"LLMAgentNode {self.node_id}: Claude CLI error: {result[:200]}")

            output: Dict[str, Any] = {"result": result, "success": success}

            # Context accumulation — only when workflow has context support
            if "context" in inputs:
                output["context"] = _accumulate_fix_context(inputs, result, success)

            return output
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
            verified = _parse_verify_verdict(response)

            message = response[:500] if len(response) > 500 else response
            output: Dict[str, Any] = {
                "verified": verified,
                "message": message,
                "details": {"full_response": response},
            }

            # Context accumulation — only when workflow has context support
            if "context" in inputs:
                output["context"] = _accumulate_verify_context(
                    inputs, verified, message,
                )

            return output

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
