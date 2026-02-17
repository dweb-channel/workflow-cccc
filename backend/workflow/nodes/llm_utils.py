"""Shared LLM utilities — Claude CLI invocation + JSON response parsing.

Provides subprocess-based Claude CLI invocation with retry/backoff,
and robust JSON extraction from LLM responses.
"""

import json
import logging
import os
import re
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


async def invoke_claude_cli(
    *,
    claude_bin: str,
    system_prompt: str,
    user_prompt: str,
    screenshot_path: str = "",
    base_dir: str = ".",
    model: str = "",
    timeout: float = 300.0,
    max_retries: int = 2,
    retry_base_delay: float = 10.0,
    component_name: str = "unknown",
    caller: str = "ClaudeCLI",
) -> Dict[str, Any]:
    """Invoke Claude CLI subprocess and return response text + token usage.

    Handles screenshot path resolution, CLI prompt assembly, subprocess
    execution with timeout, JSON envelope parsing, error detection,
    and automatic retry with exponential backoff on transient failures.

    Returns {"text": str, "token_usage": {...} | None, "retry_count": int}.
    Raises RuntimeError on CLI failure, TimeoutError on timeout (after all retries exhausted).
    """
    import asyncio

    # Resolve screenshot absolute path
    screenshot_abs = ""
    if screenshot_path:
        screenshot_abs = (
            screenshot_path
            if os.path.isabs(screenshot_path)
            else os.path.join(base_dir, screenshot_path)
        )
        if not os.path.isfile(screenshot_abs):
            logger.warning("%s: screenshot not found: %s", caller, screenshot_abs)
            screenshot_abs = ""

    # Build full CLI prompt: system + screenshot instruction + user
    cli_prompt_parts = [system_prompt, ""]
    if screenshot_abs:
        cli_prompt_parts.append(
            f"First, read the screenshot image at: {screenshot_abs}"
        )
        cli_prompt_parts.append(
            "Use this screenshot as visual reference for your analysis."
        )
        cli_prompt_parts.append("")
    cli_prompt_parts.append(user_prompt)
    cli_prompt = "\n".join(cli_prompt_parts)

    # Build CLI command
    cmd = [
        claude_bin,
        "-p", cli_prompt,
        "--output-format", "json",
        "--dangerously-skip-permissions",
        "--no-session-persistence",
    ]
    if model:
        cmd.extend(["--model", model])
    if screenshot_abs:
        cmd.extend(["--allowedTools", "Read"])
    else:
        cmd.extend(["--tools", ""])

    # Inherit env but remove CLAUDECODE to avoid nested session detection
    cli_env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}

    last_error: Optional[Exception] = None
    _is_rate_limited = False  # track if last error looked like rate limiting
    attempts = 1 + max(0, max_retries)  # at least 1 attempt
    import time as _time
    import random as _random
    _start_time = _time.monotonic()

    for attempt in range(attempts):
        if attempt > 0:
            base = retry_base_delay * (2 ** (attempt - 1))  # 10s, 20s, 40s, ...
            if _is_rate_limited:
                base = max(base, 30.0)  # rate limit: at least 30s wait
            # Add +/-25% jitter to prevent thundering herd
            delay = base * (1.0 + _random.uniform(-0.25, 0.25))
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
                continue  # retry

            raw_text = stdout.decode("utf-8", errors="replace").strip()

            # Parse CLI JSON envelope
            cli_output = None
            try:
                cli_output = json.loads(raw_text)
            except json.JSONDecodeError:
                pass

            # Check for CLI-level errors (non-zero exit or is_error in envelope)
            if proc.returncode != 0 or (
                isinstance(cli_output, dict) and cli_output.get("is_error")
            ):
                err_msg = stderr.decode("utf-8", errors="replace").strip()
                if not err_msg and isinstance(cli_output, dict):
                    err_msg = cli_output.get("result", "")
                # Detect rate limit patterns for longer backoff
                _err_lower = err_msg.lower()
                _is_rate_limited = any(
                    s in _err_lower
                    for s in ("rate", "429", "overloaded", "too many", "throttl")
                )
                last_error = RuntimeError(
                    f"Claude CLI failed (exit {proc.returncode}) for "
                    f"{component_name}: {err_msg[:500]}"
                )
                continue  # retry

            # Extract token usage from CLI JSON envelope (if available)
            token_usage: Optional[Dict[str, int]] = None
            if isinstance(cli_output, dict):
                usage = cli_output.get("usage")
                if isinstance(usage, dict):
                    token_usage = {
                        "input_tokens": usage.get("input_tokens", 0),
                        "output_tokens": usage.get("output_tokens", 0),
                    }

            # Extract the actual text content from CLI JSON envelope
            if isinstance(cli_output, dict) and "result" in cli_output:
                raw_text = cli_output["result"]
            elif isinstance(cli_output, dict) and "content" in cli_output:
                raw_text = cli_output["content"]

            duration_ms = int((_time.monotonic() - _start_time) * 1000)
            return {
                "text": raw_text,
                "token_usage": token_usage,
                "retry_count": attempt,
                "duration_ms": duration_ms,
            }

        except (TimeoutError, RuntimeError):
            raise  # already handled above via continue
        except OSError as e:
            # Subprocess spawn failure (e.g. claude binary missing mid-run)
            last_error = RuntimeError(f"CLI spawn failed for {component_name}: {e}")
            continue  # retry

    # All retries exhausted
    raise last_error or RuntimeError(
        f"Claude CLI failed after {attempts} attempts for {component_name}"
    )


def parse_llm_json(raw: str, caller: str = "LLM") -> Optional[Dict]:
    """Parse JSON from LLM response, handling markdown fences and preamble.

    Tries in order: direct parse -> strip leading fence -> regex fence -> outermost braces.
    """
    if not raw:
        return None

    text = raw.strip()

    # Strip leading markdown code fence
    if text.startswith("```"):
        lines = text.split("\n")
        lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()

    # Try direct parse
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Try extracting from non-leading markdown fence
    fence_match = re.search(r"```(?:json)?\s*\n(.*?)\n```", text, re.DOTALL)
    if fence_match:
        try:
            return json.loads(fence_match.group(1))
        except json.JSONDecodeError:
            pass

    # Fallback: extract outermost { ... }
    brace_start = text.find("{")
    brace_end = text.rfind("}")
    if brace_start >= 0 and brace_end > brace_start:
        try:
            return json.loads(text[brace_start:brace_end + 1])
        except json.JSONDecodeError:
            pass

    logger.error("%s: JSON parse error, raw[:500]: %s", caller, text[:500])
    return None


# Backward-compatible aliases (underscore-prefixed names used by spec_nodes re-exports)
_invoke_claude_cli = invoke_claude_cli
_parse_llm_json = parse_llm_json
