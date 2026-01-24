"""Claude CLI agent integration for LangGraph nodes."""
from __future__ import annotations

import asyncio
import json
from typing import AsyncGenerator, Optional


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
    output_lines = []
    async for line in stream_claude_agent(prompt, cwd, timeout):
        output_lines.append(line)
    return "\n".join(output_lines)


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
            "claude",
            "-p", prompt,
            "--output-format", "text",
            cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError:
        yield "[Error] Claude CLI not found. Please install Claude Code CLI."
        return

    try:
        async def read_stream():
            while True:
                line = await proc.stdout.readline()
                if not line:
                    break
                yield line.decode("utf-8").rstrip()

        async for line in read_stream():
            yield line

        await asyncio.wait_for(proc.wait(), timeout=timeout)

        if proc.returncode != 0:
            stderr = await proc.stderr.read()
            yield f"[Error] Claude CLI exited with code {proc.returncode}: {stderr.decode()}"

    except asyncio.TimeoutError:
        proc.kill()
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
            "claude",
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
        return {"error": "Claude CLI not found"}
    except asyncio.TimeoutError:
        return {"error": f"Timeout after {timeout}s"}
    except json.JSONDecodeError as e:
        return {"error": f"JSON parse error: {e}"}
