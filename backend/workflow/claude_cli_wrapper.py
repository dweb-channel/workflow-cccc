"""Unified Claude CLI wrapper — shared infrastructure for all CLI invocations.

Two calling modes:
- invoke_oneshot(): Single call with retry/backoff, returns {text, token_usage, ...}
- invoke_stream(): NDJSON streaming with event callbacks, returns result text

Shared: env cleanup, CLI arg construction, timeout, rate limit detection,
token/result extraction from JSON envelope.

Previously split across agents/claude.py and nodes/llm_utils.py — unified in M25/T136.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import time
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from .config import CLAUDE_CLI_PATH, CLAUDE_SKIP_PERMISSIONS, CLAUDE_MCP_CONFIG

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Shared utilities
# ---------------------------------------------------------------------------

_RATE_LIMIT_PATTERNS = ("rate", "429", "overloaded", "too many", "throttl")


def clean_env() -> Dict[str, str]:
    """Inherit env but remove CLAUDECODE to avoid nested session detection."""
    return {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}


def build_cli_args(
    prompt: str,
    *,
    claude_bin: str = "",
    output_format: str = "json",
    model: str = "",
    verbose: bool = False,
    no_session_persistence: bool = True,
    allowed_tools: Optional[List[str]] = None,
    no_tools: bool = False,
) -> List[str]:
    """Build CLI argument list with common flags.

    Centralizes all flag construction so every invocation site uses consistent flags.
    """
    bin_path = claude_bin or CLAUDE_CLI_PATH
    args = [bin_path, "-p", prompt, "--output-format", output_format]
    if verbose:
        args.append("--verbose")
    if CLAUDE_SKIP_PERMISSIONS:
        args.append("--dangerously-skip-permissions")
    if CLAUDE_MCP_CONFIG:
        args.extend(["--mcp-config", CLAUDE_MCP_CONFIG])
    if model:
        args.extend(["--model", model])
    if no_session_persistence:
        args.append("--no-session-persistence")
    if allowed_tools:
        args.extend(["--allowedTools"] + allowed_tools)
    elif no_tools:
        args.extend(["--tools", ""])
    return args


def is_rate_limit_error(error_msg: str) -> bool:
    """Detect rate limit patterns in error messages."""
    lower = error_msg.lower()
    return any(p in lower for p in _RATE_LIMIT_PATTERNS)


def extract_token_usage(cli_output: dict) -> Optional[Dict[str, int]]:
    """Extract token usage from CLI JSON envelope."""
    usage = cli_output.get("usage")
    if isinstance(usage, dict):
        return {
            "input_tokens": usage.get("input_tokens", 0),
            "output_tokens": usage.get("output_tokens", 0),
        }
    return None


def extract_result_text(raw_text: str, cli_output: Optional[dict]) -> str:
    """Extract result text from CLI JSON envelope, falling back to raw text."""
    if isinstance(cli_output, dict):
        if "result" in cli_output:
            return cli_output["result"]
        if "content" in cli_output:
            return cli_output["content"]
    return raw_text


def resolve_screenshot(screenshot_path: str, base_dir: str, caller: str) -> str:
    """Resolve screenshot path to absolute, returning '' if not found."""
    if not screenshot_path:
        return ""
    abs_path = (
        screenshot_path
        if os.path.isabs(screenshot_path)
        else os.path.join(base_dir, screenshot_path)
    )
    if not os.path.isfile(abs_path):
        logger.warning("%s: screenshot not found: %s", caller, abs_path)
        return ""
    return abs_path


# ---------------------------------------------------------------------------
# Structured Event Types (used by streaming mode)
# ---------------------------------------------------------------------------

class ClaudeEvent:
    """Structured event from Claude CLI stream-json output."""

    THINKING = "thinking"
    TOOL_USE = "tool_use"
    TEXT = "text"
    RESULT = "result"

    __slots__ = ("type", "content", "tool_name", "tool_input", "timestamp",
                 "is_error", "usage", "cost_usd", "duration_ms")

    def __init__(
        self,
        type: str,
        content: str = "",
        tool_name: Optional[str] = None,
        tool_input: Optional[Dict[str, Any]] = None,
        timestamp: Optional[str] = None,
        is_error: bool = False,
        usage: Optional[Dict[str, Any]] = None,
        cost_usd: Optional[float] = None,
        duration_ms: Optional[float] = None,
    ):
        self.type = type
        self.content = content
        self.tool_name = tool_name
        self.tool_input = tool_input
        self.timestamp = timestamp or datetime.now(timezone.utc).isoformat()
        self.is_error = is_error
        self.usage = usage
        self.cost_usd = cost_usd
        self.duration_ms = duration_ms

    def to_dict(self) -> Dict[str, Any]:
        """Convert to SSE-ready dict."""
        d: Dict[str, Any] = {
            "type": self.type,
            "content": self.content,
            "timestamp": self.timestamp,
        }
        if self.tool_name is not None:
            d["tool_name"] = self.tool_name
        if self.tool_input is not None:
            d["tool_input"] = self.tool_input
        if self.is_error:
            d["is_error"] = True
        if self.usage is not None:
            d["usage"] = self.usage
        if self.cost_usd is not None:
            d["cost_usd"] = self.cost_usd
        if self.duration_ms is not None:
            d["duration_ms"] = self.duration_ms
        return d


def _parse_assistant_content(content_blocks: list) -> list[ClaudeEvent]:
    """Extract structured events from assistant message content blocks."""
    events = []
    now = datetime.now(timezone.utc).isoformat()
    for block in content_blocks:
        block_type = block.get("type", "")
        if block_type == "thinking":
            events.append(ClaudeEvent(
                type=ClaudeEvent.THINKING,
                content=block.get("thinking", ""),
                timestamp=now,
            ))
        elif block_type == "tool_use":
            tool_input = block.get("input", {})
            content_summary = json.dumps(tool_input, ensure_ascii=False)
            if len(content_summary) > 500:
                content_summary = content_summary[:500] + "..."
            events.append(ClaudeEvent(
                type=ClaudeEvent.TOOL_USE,
                content=content_summary,
                tool_name=block.get("name", "unknown"),
                tool_input=tool_input,
                timestamp=now,
            ))
        elif block_type == "text":
            text = block.get("text", "")
            if text.strip():
                events.append(ClaudeEvent(
                    type=ClaudeEvent.TEXT,
                    content=text,
                    timestamp=now,
                ))
    return events


# ---------------------------------------------------------------------------
# High-level API: Oneshot invocation (replaces llm_utils.invoke_claude_cli)
# ---------------------------------------------------------------------------

async def invoke_oneshot(
    *,
    prompt: str,
    claude_bin: str = "",
    cwd: str = ".",
    model: str = "",
    timeout: float = 300.0,
    max_retries: int = 2,
    retry_base_delay: float = 10.0,
    screenshot_path: str = "",
    allowed_tools: Optional[List[str]] = None,
    no_tools: bool = False,
    component_name: str = "unknown",
    caller: str = "ClaudeCLI",
) -> Dict[str, Any]:
    """Oneshot Claude CLI invocation with retry and exponential backoff.

    Builds prompt (including screenshot instructions if provided), invokes
    Claude CLI as a subprocess, parses the JSON envelope, and extracts
    text + token usage.

    Returns {"text": str, "token_usage": dict|None, "retry_count": int, "duration_ms": int}.
    Raises RuntimeError on CLI failure, TimeoutError on timeout (after all retries).
    """
    # Resolve screenshot absolute path
    screenshot_abs = resolve_screenshot(screenshot_path, cwd, caller)

    # Build full prompt with screenshot instruction if applicable
    if screenshot_abs:
        full_prompt = (
            f"{prompt}\n\n"
            f"First, read the screenshot image at: {screenshot_abs}\n"
            "Use this screenshot as visual reference for your analysis."
        )
        tools = allowed_tools or ["Read"]
    else:
        full_prompt = prompt
        tools = allowed_tools

    # Build CLI command
    cmd = build_cli_args(
        full_prompt,
        claude_bin=claude_bin,
        output_format="json",
        model=model,
        no_session_persistence=True,
        allowed_tools=tools,
        no_tools=no_tools if not tools else False,
    )

    cli_env = clean_env()

    last_error: Optional[Exception] = None
    _is_rate_limited = False
    attempts = 1 + max(0, max_retries)
    _start_time = time.monotonic()

    for attempt in range(attempts):
        if attempt > 0:
            base = retry_base_delay * (2 ** (attempt - 1))
            if _is_rate_limited:
                base = max(base, 30.0)
            delay = base * (1.0 + random.uniform(-0.25, 0.25))
            logger.warning(
                "%s: retry %d/%d for %s after %.1fs%s (previous error: %s)",
                caller, attempt, max_retries, component_name, delay,
                " [rate-limited]" if _is_rate_limited else "",
                last_error,
            )
            await asyncio.sleep(delay)

        logger.info(
            "%s: calling claude CLI for %s (attempt %d/%d)",
            caller, component_name, attempt + 1, attempts,
        )

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=cli_env,
            )

            try:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(), timeout=timeout,
                )
            except asyncio.TimeoutError:
                proc.kill()
                await proc.communicate()
                last_error = TimeoutError(
                    f"Claude CLI timed out ({timeout}s) for {component_name}"
                )
                continue

            raw_text = stdout.decode("utf-8", errors="replace").strip()

            # Parse CLI JSON envelope
            cli_output = None
            try:
                cli_output = json.loads(raw_text)
            except json.JSONDecodeError:
                pass

            # Check for CLI-level errors
            if proc.returncode != 0 or (
                isinstance(cli_output, dict) and cli_output.get("is_error")
            ):
                err_msg = stderr.decode("utf-8", errors="replace").strip()
                if not err_msg and isinstance(cli_output, dict):
                    err_msg = cli_output.get("result", "")
                _is_rate_limited = is_rate_limit_error(err_msg)
                last_error = RuntimeError(
                    f"Claude CLI failed (exit {proc.returncode}) for "
                    f"{component_name}: {err_msg[:500]}"
                )
                continue

            # Extract token usage and result text
            token_usage = extract_token_usage(cli_output) if isinstance(cli_output, dict) else None
            result_text = extract_result_text(raw_text, cli_output)

            duration_ms = int((time.monotonic() - _start_time) * 1000)
            return {
                "text": result_text,
                "token_usage": token_usage,
                "retry_count": attempt,
                "duration_ms": duration_ms,
            }

        except (TimeoutError, RuntimeError):
            raise
        except OSError as e:
            last_error = RuntimeError(f"CLI spawn failed for {component_name}: {e}")
            continue

    raise last_error or RuntimeError(
        f"Claude CLI failed after {attempts} attempts for {component_name}"
    )


# ---------------------------------------------------------------------------
# High-level API: Streaming invocation (replaces agents/claude.stream_claude_events)
# ---------------------------------------------------------------------------

async def invoke_stream(
    prompt: str,
    cwd: str = ".",
    timeout: float = 300.0,
    on_event: Optional[Callable[[ClaudeEvent], None]] = None,
) -> str:
    """Run Claude CLI with stream-json and emit structured events.

    Uses --output-format stream-json --verbose to get NDJSON events.
    Parses assistant/result events and calls on_event for each structured event.
    Returns the final result text.
    """
    cmd = build_cli_args(
        prompt,
        output_format="stream-json",
        verbose=True,
        no_session_persistence=False,  # batch workflow uses sessions
    )
    cli_env = clean_env()

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=cli_env,
        )
    except FileNotFoundError:
        msg = f"[Error] Claude CLI not found at '{CLAUDE_CLI_PATH}'. Set CLAUDE_CLI_PATH env var."
        if on_event:
            on_event(ClaudeEvent(type=ClaudeEvent.RESULT, content=msg, is_error=True))
        return msg

    result_text = ""
    deadline = asyncio.get_event_loop().time() + timeout

    try:
        while True:
            remaining = deadline - asyncio.get_event_loop().time()
            if remaining <= 0:
                raise asyncio.TimeoutError()
            try:
                line = await asyncio.wait_for(
                    proc.stdout.readline(),
                    timeout=remaining,
                )
            except asyncio.TimeoutError:
                raise
            if not line:
                break

            line_str = line.decode("utf-8").rstrip()
            if not line_str:
                continue

            try:
                data = json.loads(line_str)
            except json.JSONDecodeError:
                logger.debug("invoke_stream: non-JSON line: %s", line_str[:100])
                continue

            msg_type = data.get("type", "")

            if msg_type == "assistant":
                message = data.get("message", {})
                content_blocks = message.get("content", [])
                events = _parse_assistant_content(content_blocks)
                if on_event:
                    for evt in events:
                        on_event(evt)

            elif msg_type == "user":
                message = data.get("message", {})
                content_blocks = message.get("content", [])
                for block in content_blocks:
                    if block.get("type") == "tool_result":
                        tool_content = block.get("content", "")
                        if isinstance(tool_content, str) and tool_content.strip():
                            preview = tool_content[:500]
                            if len(tool_content) > 500:
                                preview += "..."
                            if on_event:
                                on_event(ClaudeEvent(
                                    type=ClaudeEvent.TEXT,
                                    content=f"[Tool Result] {preview}",
                                ))

            elif msg_type == "result":
                is_error = data.get("is_error", False)
                result_text = data.get("result", "")
                usage = data.get("usage", {})
                cost_usd = data.get("total_cost_usd")
                duration_ms = data.get("duration_ms")

                if on_event:
                    on_event(ClaudeEvent(
                        type=ClaudeEvent.RESULT,
                        content=result_text[:500] if len(result_text) > 500 else result_text,
                        is_error=is_error,
                        usage=usage,
                        cost_usd=cost_usd,
                        duration_ms=duration_ms,
                    ))

        # Wait for process to finish
        remaining = deadline - asyncio.get_event_loop().time()
        if remaining > 0:
            await asyncio.wait_for(proc.wait(), timeout=remaining)
        else:
            raise asyncio.TimeoutError()

        if proc.returncode != 0 and not result_text:
            stderr_bytes = await proc.stderr.read()
            err_msg = f"[Error] Claude CLI exited with code {proc.returncode}: {stderr_bytes.decode()}"
            if on_event:
                on_event(ClaudeEvent(type=ClaudeEvent.RESULT, content=err_msg, is_error=True))
            return err_msg

        return result_text or "[Error] No result received from Claude CLI"

    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        msg = f"[Error] Claude CLI timed out after {timeout}s"
        if on_event:
            on_event(ClaudeEvent(type=ClaudeEvent.RESULT, content=msg, is_error=True))
        return msg
