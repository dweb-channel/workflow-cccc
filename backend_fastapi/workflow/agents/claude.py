"""Claude CLI agent integration for LangGraph nodes."""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any, AsyncGenerator, Callable, Dict, Optional

from ..config import CLAUDE_CLI_PATH

logger = logging.getLogger(__name__)


async def run_claude_agent(
    prompt: str,
    cwd: str = ".",
    timeout: float = 300.0,
) -> str:
    """Run Claude CLI and return the complete output.

    Args:
        prompt: The prompt to send to Claude
        cwd: Working directory for the command
        timeout: Maximum execution time in seconds

    Returns:
        The complete output from Claude CLI
    """
    try:
        proc = await asyncio.create_subprocess_exec(
            CLAUDE_CLI_PATH,
            "-p", prompt,
            "--output-format", "text",
            cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError:
        return f"[Error] Claude CLI not found at '{CLAUDE_CLI_PATH}'. Set CLAUDE_CLI_PATH env var."

    try:
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(),
            timeout=timeout,
        )

        output = stdout.decode("utf-8").rstrip()

        if proc.returncode != 0:
            err_msg = stderr.decode("utf-8").rstrip()
            return f"[Error] Claude CLI exited with code {proc.returncode}: {err_msg}"

        return output

    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        return f"[Error] Claude CLI timed out after {timeout}s"


async def stream_claude_agent(
    prompt: str,
    cwd: str = ".",
    timeout: float = 300.0,
) -> AsyncGenerator[str, None]:
    """Stream Claude CLI output line by line.

    Args:
        prompt: The prompt to send to Claude
        cwd: Working directory for the command
        timeout: Maximum execution time in seconds

    Yields:
        Output lines from Claude CLI as they become available
    """
    try:
        proc = await asyncio.create_subprocess_exec(
            CLAUDE_CLI_PATH,
            "-p", prompt,
            "--output-format", "text",
            cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError:
        yield f"[Error] Claude CLI not found at '{CLAUDE_CLI_PATH}'. Set CLAUDE_CLI_PATH env var."
        return

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
            yield line.decode("utf-8").rstrip()

        remaining = deadline - asyncio.get_event_loop().time()
        if remaining > 0:
            await asyncio.wait_for(proc.wait(), timeout=remaining)
        else:
            raise asyncio.TimeoutError()

        if proc.returncode != 0:
            stderr = await proc.stderr.read()
            yield f"[Error] Claude CLI exited with code {proc.returncode}: {stderr.decode()}"

    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        yield f"[Error] Claude CLI timed out after {timeout}s"


async def run_claude_agent_json(
    prompt: str,
    cwd: str = ".",
    timeout: float = 300.0,
) -> Optional[dict]:
    """Run Claude CLI and parse JSON output.

    Args:
        prompt: The prompt to send to Claude
        cwd: Working directory for the command
        timeout: Maximum execution time in seconds

    Returns:
        Parsed JSON output or None if parsing fails
    """
    try:
        proc = await asyncio.create_subprocess_exec(
            CLAUDE_CLI_PATH,
            "-p", prompt,
            "--output-format", "json",
            cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        stdout, stderr = await asyncio.wait_for(
            proc.communicate(),
            timeout=timeout,
        )

        if proc.returncode != 0:
            return {"error": stderr.decode(), "code": proc.returncode}

        return json.loads(stdout.decode())

    except FileNotFoundError:
        return {"error": f"Claude CLI not found at '{CLAUDE_CLI_PATH}'"}
    except asyncio.TimeoutError:
        return {"error": f"Timeout after {timeout}s"}
    except json.JSONDecodeError as e:
        return {"error": f"JSON parse error: {e}"}


# --- Structured Event Types ---

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
    """Extract structured events from assistant message content blocks.

    Maps:
    - type=="thinking" → ClaudeEvent.THINKING
    - type=="tool_use" → ClaudeEvent.TOOL_USE
    - type=="text" → ClaudeEvent.TEXT
    """
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
            # Summarize tool input for display
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


async def stream_claude_events(
    prompt: str,
    cwd: str = ".",
    timeout: float = 300.0,
    on_event: Optional[Callable[[ClaudeEvent], None]] = None,
) -> str:
    """Run Claude CLI with stream-json and emit structured events.

    Uses --output-format stream-json --verbose to get NDJSON events.
    Parses assistant/result events and calls on_event for each structured event.
    Returns the final result text (same contract as run_claude_agent).

    Args:
        prompt: The prompt to send to Claude
        cwd: Working directory for the command
        timeout: Maximum execution time in seconds
        on_event: Optional callback for each structured event (for SSE push)

    Returns:
        The complete output from Claude CLI (result text)
    """
    try:
        proc = await asyncio.create_subprocess_exec(
            CLAUDE_CLI_PATH,
            "-p", prompt,
            "--output-format", "stream-json",
            "--verbose",
            cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
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

            # Parse NDJSON line
            line_str = line.decode("utf-8").rstrip()
            if not line_str:
                continue

            try:
                data = json.loads(line_str)
            except json.JSONDecodeError:
                logger.debug(f"stream_claude_events: non-JSON line: {line_str[:100]}")
                continue

            msg_type = data.get("type", "")

            if msg_type == "assistant":
                # Extract content blocks from assistant message
                message = data.get("message", {})
                content_blocks = message.get("content", [])
                events = _parse_assistant_content(content_blocks)
                if on_event:
                    for evt in events:
                        on_event(evt)

            elif msg_type == "user":
                # Tool results — extract content for display
                message = data.get("message", {})
                content_blocks = message.get("content", [])
                for block in content_blocks:
                    if block.get("type") == "tool_result":
                        tool_content = block.get("content", "")
                        if isinstance(tool_content, str) and tool_content.strip():
                            # Truncate large tool results
                            preview = tool_content[:500]
                            if len(tool_content) > 500:
                                preview += "..."
                            if on_event:
                                on_event(ClaudeEvent(
                                    type=ClaudeEvent.TEXT,
                                    content=f"[Tool Result] {preview}",
                                ))

            elif msg_type == "result":
                # Final result event
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
