"""Claude CLI agent integration for LangGraph nodes.

Delegates to the unified claude_cli_wrapper for subprocess management.
This module preserves the public API used by workflow/nodes/agents.py.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, AsyncGenerator, Callable, Dict, List, Optional

from ..claude_cli_wrapper import (
    ClaudeEvent,
    build_cli_args,
    clean_env,
    invoke_stream,
    _parse_assistant_content,
)
from ..config import CLAUDE_CLI_PATH

logger = logging.getLogger(__name__)


# Re-export ClaudeEvent so existing `from ..agents.claude import ClaudeEvent` works
__all__ = [
    "ClaudeEvent",
    "run_claude_agent",
    "stream_claude_agent",
    "run_claude_agent_json",
    "stream_claude_events",
]


async def run_claude_agent(
    prompt: str,
    cwd: str = ".",
    timeout: float = 300.0,
) -> str:
    """Run Claude CLI and return the complete output."""
    cmd = build_cli_args(prompt, output_format="text", no_session_persistence=False)
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
    """Stream Claude CLI output line by line."""
    cmd = build_cli_args(prompt, output_format="text", no_session_persistence=False)
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
    """Run Claude CLI and parse JSON output."""
    cmd = build_cli_args(prompt, output_format="json", no_session_persistence=False)
    cli_env = clean_env()
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=cli_env,
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


async def stream_claude_events(
    prompt: str,
    cwd: str = ".",
    timeout: float = 300.0,
    on_event: Optional[Callable[[ClaudeEvent], None]] = None,
) -> str:
    """Run Claude CLI with stream-json and emit structured events.

    Delegates to claude_cli_wrapper.invoke_stream().
    """
    return await invoke_stream(prompt, cwd=cwd, timeout=timeout, on_event=on_event)
