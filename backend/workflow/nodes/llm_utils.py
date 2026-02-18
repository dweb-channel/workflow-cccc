"""Shared LLM utilities — Claude CLI invocation + JSON response parsing.

CLI invocation delegates to the unified claude_cli_wrapper.
JSON parsing (sanitize, multi-stage recovery) remains here as it's
specific to LLM response processing, not CLI subprocess management.
"""

import json
import logging
import re
from typing import Any, Dict, Optional

from ..claude_cli_wrapper import invoke_oneshot

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

    Delegates to claude_cli_wrapper.invoke_oneshot() for subprocess management,
    retry, backoff, rate limit detection, and token extraction.

    Returns {"text": str, "token_usage": {...} | None, "retry_count": int}.
    Raises RuntimeError on CLI failure, TimeoutError on timeout (after all retries).
    """
    # Build full prompt: system + user
    full_prompt = f"{system_prompt}\n\n{user_prompt}"

    # Determine tool restrictions based on screenshot
    allowed_tools = ["Read"] if screenshot_path else None
    no_tools = not screenshot_path

    return await invoke_oneshot(
        prompt=full_prompt,
        claude_bin=claude_bin,
        cwd=base_dir,
        model=model,
        timeout=timeout,
        max_retries=max_retries,
        retry_base_delay=retry_base_delay,
        screenshot_path=screenshot_path,
        allowed_tools=allowed_tools,
        no_tools=no_tools,
        component_name=component_name,
        caller=caller,
    )


def _sanitize_llm_json(text: str, caller: str = "LLM") -> str:
    """Sanitize common LLM JSON errors before parsing.

    Fixes (in order):
    1. Control characters (except tab/newline/cr)
    2. Chinese/smart quotes -> ASCII quotes
    3. Trailing commas in objects/arrays
    4. Truncated JSON auto-closing (unmatched braces/brackets)

    Logs a warning when non-trivial repairs are applied (truncation auto-close).
    """
    repairs: list[str] = []

    # 1. Strip control characters (keep \t \n \r)
    cleaned = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text)
    if cleaned != text:
        repairs.append("control_chars")
    text = cleaned

    # 2. Replace Chinese/smart quotes with ASCII equivalents
    text = text.replace("\u201c", '"').replace("\u201d", '"')  # "" -> "
    text = text.replace("\u2018", "'").replace("\u2019", "'")  # '' -> '
    text = text.replace("\u300c", '"').replace("\u300d", '"')  # 「」-> "
    text = text.replace("\u300e", '"').replace("\u300f", '"')  # 『』-> "

    # 3. Remove trailing commas before } or ]
    new_text = re.sub(r",\s*([}\]])", r"\1", text)
    if new_text != text:
        repairs.append("trailing_commas")
    text = new_text

    # 4. Auto-close truncated JSON (unmatched { and [)
    in_string = False
    escape = False
    stack: list[str] = []
    for ch in text:
        if escape:
            escape = False
            continue
        if ch == "\\":
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch in ("{", "["):
            stack.append(ch)
        elif ch == "}" and stack and stack[-1] == "{":
            stack.pop()
        elif ch == "]" and stack and stack[-1] == "[":
            stack.pop()
    if stack:
        repairs.append(f"auto_closed_{len(stack)}_brackets")
        text = text.rstrip()
        for opener in reversed(stack):
            text += "}" if opener == "{" else "]"

    # Log warning for non-trivial repairs (auto-close is the risky one)
    if repairs:
        logger.warning(
            "%s: _sanitize_llm_json applied repairs: %s (text length=%d)",
            caller, ", ".join(repairs), len(text),
        )

    return text


def parse_llm_json(raw: str, caller: str = "LLM") -> Optional[Dict]:
    """Parse JSON from LLM response, handling markdown fences and preamble.

    Pipeline:
    1. Direct parse
    2. Strip leading markdown fence -> parse
    3. Regex extract from non-leading fence -> parse
    4. Sanitize (smart quotes, trailing commas, control chars, truncation) -> parse
    5. Extract outermost { ... } -> sanitize -> parse
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

    # Sanitize and retry
    sanitized = _sanitize_llm_json(text, caller=caller)
    try:
        return json.loads(sanitized)
    except json.JSONDecodeError:
        pass

    # Fallback: extract outermost { ... } then sanitize
    brace_start = sanitized.find("{")
    brace_end = sanitized.rfind("}")
    if brace_start >= 0 and brace_end > brace_start:
        extracted = sanitized[brace_start:brace_end + 1]
        try:
            return json.loads(extracted)
        except json.JSONDecodeError:
            # Last resort: sanitize the extracted portion again
            try:
                return json.loads(_sanitize_llm_json(extracted, caller=caller))
            except json.JSONDecodeError:
                pass

    logger.error("%s: JSON parse error, raw[:500]: %s", caller, text[:500])
    return None


# Backward-compatible aliases (underscore-prefixed names used by spec_nodes re-exports)
_invoke_claude_cli = invoke_claude_cli
_parse_llm_json = parse_llm_json
