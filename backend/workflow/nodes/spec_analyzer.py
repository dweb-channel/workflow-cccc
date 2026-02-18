"""Node 2: SpecAnalyzerNode — Two-pass LLM analysis for semantic fields.

Two-pass architecture:
  Pass 1: Screenshot + structural spec → free-form design analysis (Chinese markdown)
  Pass 2: Pass 1 analysis + spec → small JSON metadata (role, name, interaction, etc.)

design_analysis comes from Pass 1 (never serialized as JSON).
Structured fields come from Pass 2 (small JSON, sanitize + retry safety net).
"""

import json
import logging
from typing import Any, Dict, List

from .registry import BaseNodeImpl, register_node_type
from .llm_utils import invoke_claude_cli as _invoke_claude_cli
from .llm_utils import parse_llm_json as _parse_llm_json

# Import two-pass prompt templates and merger
from ..spec.spec_analyzer_prompt import (
    PASS1_SYSTEM_PROMPT,
    PASS1_USER_PROMPT,
    PASS2_SYSTEM_PROMPT,
    PASS2_USER_PROMPT,
)
from ..spec.spec_merger import merge_analyzer_output

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers: strip semantic fields for partial spec
# ---------------------------------------------------------------------------


def _strip_semantic_fields(spec: Dict) -> Dict:
    """Create a copy of ComponentSpec with semantic fields nulled out.

    This is the 'partial spec' sent to the LLM -- structural data only.
    """
    result = {}
    for key, value in spec.items():
        if key in ("role", "description", "render_hint"):
            result[key] = None  # LLM will fill these
        elif key == "interaction":
            result[key] = None
        elif key == "children":
            result[key] = [
                _strip_semantic_fields(c) if isinstance(c, dict) else c
                for c in value
            ]
        else:
            result[key] = value
    return result


# ---------------------------------------------------------------------------
# Node 2: SpecAnalyzerNode
# ---------------------------------------------------------------------------

@register_node_type(
    node_type="spec_analyzer",
    display_name="Spec Analyzer",
    description=(
        "Uses Claude CLI with vision to fill semantic fields "
        "(role, description, interaction) in ComponentSpecs. "
        "Processes each frame with screenshot + partial spec."
    ),
    category="analysis",
    input_schema={
        "type": "object",
        "properties": {
            "components": {
                "type": "array",
                "description": (
                    "List of partial ComponentSpec dicts from FrameDecomposer"
                ),
            },
            "page": {"type": "object"},
            "design_tokens": {"type": "object"},
            "source": {"type": "object"},
        },
    },
    output_schema={
        "type": "object",
        "properties": {
            "components": {
                "type": "array",
                "description": "ComponentSpecs with semantic fields filled",
            },
            "analysis_stats": {"type": "object"},
        },
    },
    icon="scan-eye",
    color="#8B5CF6",
)
class SpecAnalyzerNode(BaseNodeImpl):
    """Node 2: SpecAnalyzer -- LLM vision analysis for semantic fields.

    For each top-level component:
    1. Resolves screenshot absolute path
    2. Builds prompt (partial spec JSON + page context + screenshot ref)
    3. Calls Claude CLI subprocess with vision (Read tool for images)
    4. Parses returned JSON, merges into ComponentSpec
    5. Sends SSE event per completed component
    """

    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        components = inputs.get("components", [])
        page = inputs.get("page", {})
        design_tokens = inputs.get("design_tokens", {})
        source = inputs.get("source", {})
        run_id = inputs.get("run_id", "")
        cwd = self.config.get("cwd", ".")

        model = self.config.get("model", "")
        max_tokens = self.config.get("max_tokens", 4096)

        logger.info(
            "SpecAnalyzerNode [%s]: analyzing %d components with %s",
            self.node_id, len(components), model,
        )

        # Build page context for prompt
        device = page.get("device", {})
        page_layout = page.get("layout", {})
        sibling_names = [c.get("name", "?") for c in components]

        # Verify claude CLI is available
        import shutil
        claude_bin = shutil.which("claude")
        if not claude_bin:
            logger.error(
                "SpecAnalyzerNode: 'claude' CLI not found in PATH. "
                "Install Claude Code: https://code.claude.com"
            )
            return {
                "components": components,
                "analysis_stats": {"error": "claude CLI not found in PATH"},
            }

        # Read max_retries from config (passed through from API)
        max_retries = self.config.get("max_retries", 2)

        stats = {
            "total": len(components), "succeeded": 0, "failed": 0,
            "total_retries": 0,
        }
        token_totals = {"input_tokens": 0, "output_tokens": 0}

        # Concurrent analysis with semaphore to limit parallel CLI processes
        import asyncio
        from ..settings import SPEC_CLI_CONCURRENCY, SPEC_COMPONENT_STAGGER_DELAY
        sem = asyncio.Semaphore(SPEC_CLI_CONCURRENCY)

        async def _analyze_one(idx: int, component: Dict) -> Dict:
            comp_name = component.get("name", f"component_{idx}")
            comp_id = component.get("id", "")
            # Stagger launches to avoid hitting rate limits
            if idx > 0:
                await asyncio.sleep(idx * SPEC_COMPONENT_STAGGER_DELAY)
            logger.info(
                "SpecAnalyzerNode [%s]: analyzing %s (%d/%d)",
                self.node_id, comp_name, idx + 1, len(components),
            )
            async with sem:
                try:
                    result = await self._analyze_single_component(
                        claude_bin=claude_bin,
                        component=component,
                        page=page,
                        design_tokens=design_tokens,
                        device=device,
                        page_layout=page_layout,
                        sibling_names=sibling_names,
                        cwd=cwd,
                        model=model,
                        max_retries=max_retries,
                    )
                    stats["succeeded"] += 1

                    # Track retries and duration
                    retry_count = result.pop("_retry_count", 0)
                    stats["total_retries"] += retry_count
                    duration_ms = result.pop("_duration_ms", 0)

                    # Accumulate token usage
                    comp_tokens = result.pop("_token_usage", None)
                    if comp_tokens:
                        token_totals["input_tokens"] += comp_tokens.get("input_tokens", 0)
                        token_totals["output_tokens"] += comp_tokens.get("output_tokens", 0)

                    # Push SSE event for this component.
                    # Uses HTTP POST (workflow/sse.py) since this runs in
                    # Temporal Worker process — reverted from T137's direct
                    # EventBus push after T141 Temporal migration.
                    if run_id:
                        from ..sse import push_sse_event
                        sse_payload: Dict[str, Any] = {
                            "component_id": comp_id,
                            "component_name": comp_name,
                            "suggested_name": result.get("suggested_name"),
                            "role": result.get("role"),
                            "description": result.get("description", "")[:200],
                            "design_analysis": result.get("design_analysis"),
                            "index": idx,
                            "total": len(components),
                            "duration_ms": duration_ms,
                        }
                        if comp_tokens:
                            sse_payload["tokens_used"] = comp_tokens
                        if retry_count > 0:
                            sse_payload["retry_count"] = retry_count
                        await push_sse_event(run_id, "spec_analyzed", sse_payload)

                    return result
                except Exception as e:
                    logger.error(
                        "SpecAnalyzerNode [%s]: failed to analyze %s: %s",
                        self.node_id, comp_name, e,
                    )
                    stats["failed"] += 1
                    return {**component, "_analysis_failed": True}

        raw_results = await asyncio.gather(
            *[_analyze_one(i, c) for i, c in enumerate(components)],
            return_exceptions=True,
        )
        # Handle exceptions returned by return_exceptions=True
        analyzed_components = []
        for i, r in enumerate(raw_results):
            if isinstance(r, BaseException):
                comp = components[i]
                logger.error(
                    "SpecAnalyzerNode [%s]: component %s raised %s: %s",
                    self.node_id, comp.get("name", f"component_{i}"),
                    type(r).__name__, r,
                )
                stats["failed"] += 1
                analyzed_components.append({**comp, "_analysis_failed": True})
            else:
                analyzed_components.append(r)

        logger.info(
            "SpecAnalyzerNode [%s]: done -- %d/%d succeeded, tokens: %d in / %d out",
            self.node_id, stats["succeeded"], stats["total"],
            token_totals["input_tokens"], token_totals["output_tokens"],
        )

        return {
            "components": analyzed_components,
            "analysis_stats": stats,
            "token_usage": token_totals,
        }

    async def _retry_with_error_feedback(
        self,
        claude_bin: str,
        raw_text: str,
        cwd: str,
        model: str,
        component_name: str,
    ) -> dict | None:
        """Retry JSON parse by feeding the error back to Claude CLI.

        Sends the malformed output + parse error to Claude, asking it to
        return only the corrected JSON. Single retry, no screenshot needed
        since the model already has context from the original response.
        """
        # Try to get a specific parse error message
        import json as _json
        parse_error = "Could not parse as JSON"
        try:
            _json.loads(raw_text)
        except _json.JSONDecodeError as e:
            parse_error = str(e)

        # Truncate raw_text to avoid hitting token limits
        truncated = raw_text[:3000] if len(raw_text) > 3000 else raw_text

        correction_prompt = (
            "Your previous response could not be parsed as valid JSON.\n\n"
            f"Parse error: {parse_error}\n\n"
            f"Your previous output (may be truncated):\n{truncated}\n\n"
            "Please return ONLY the corrected valid JSON object. "
            "The first character must be { and the last must be }. "
            "No markdown, no code fences, no explanation. "
            "Fix any escaping issues in string values "
            "(use \\n for newlines, \\\" for quotes inside strings)."
        )

        try:
            correction_result = await _invoke_claude_cli(
                claude_bin=claude_bin,
                system_prompt="You are a JSON repair assistant. Return only valid JSON.",
                user_prompt=correction_prompt,
                base_dir=cwd,
                model=model,
                timeout=120.0,
                max_retries=0,  # no further retries for the correction call
                component_name=f"{component_name}_json_fix",
                caller=f"SpecAnalyzerNode [{self.node_id}] retry",
            )
            corrected = _parse_llm_json(
                correction_result["text"],
                caller=f"SpecAnalyzerNode [{self.node_id}] retry",
            )
            if corrected:
                logger.info(
                    "SpecAnalyzerNode [%s]: retry succeeded for %s",
                    self.node_id, component_name,
                )
            return corrected
        except Exception as e:
            logger.error(
                "SpecAnalyzerNode [%s]: retry failed for %s: %s",
                self.node_id, component_name, e,
            )
            return None

    async def _analyze_single_component(
        self,
        claude_bin: str,
        component: Dict,
        page: Dict,
        design_tokens: Dict,
        device: Dict,
        page_layout: Dict,
        sibling_names: List[str],
        cwd: str,
        model: str,
        max_retries: int = 2,
    ) -> Dict:
        """Analyze a single component using two-pass Claude CLI architecture.

        Pass 1: Screenshot + structural spec → free-form design analysis text
        Pass 2: Pass 1 text + spec → small JSON (role, name, interaction, etc.)
        """
        import time as _time
        _start_time = _time.monotonic()

        comp_name = component.get("name", "?")

        # Build partial spec (structural data only)
        partial_spec = _strip_semantic_fields(component)
        partial_spec_json = json.dumps(partial_spec, ensure_ascii=False, indent=2)
        tokens_json = json.dumps(design_tokens, ensure_ascii=False, indent=2)
        sibling_names_str = ", ".join(sibling_names)

        # Token usage accumulator for both passes
        total_tokens: Dict[str, int] = {"input_tokens": 0, "output_tokens": 0}
        total_retries = 0

        # ---- Pass 1: Free-form design analysis (with screenshot) ----
        pass1_user = PASS1_USER_PROMPT.format(
            device_type=device.get("type", "mobile"),
            device_width=device.get("width", 393),
            device_height=device.get("height", 852),
            responsive_strategy=page.get("responsive_strategy", "fixed-width"),
            page_layout_type=page_layout.get("type", "flex"),
            sibling_names=sibling_names_str,
            design_tokens_json=tokens_json,
            partial_spec_json=partial_spec_json,
        )

        pass1_result = await _invoke_claude_cli(
            claude_bin=claude_bin,
            system_prompt=PASS1_SYSTEM_PROMPT,
            user_prompt=pass1_user,
            screenshot_path=component.get("screenshot_path", ""),
            base_dir=cwd,
            model=model,
            timeout=300.0,
            max_retries=max_retries,
            component_name=f"{comp_name}_pass1",
            caller=f"SpecAnalyzerNode [{self.node_id}]",
        )

        design_analysis_text = pass1_result["text"]
        total_retries += pass1_result.get("retry_count", 0)
        if pass1_result["token_usage"]:
            total_tokens["input_tokens"] += pass1_result["token_usage"].get("input_tokens", 0)
            total_tokens["output_tokens"] += pass1_result["token_usage"].get("output_tokens", 0)

        logger.info(
            "SpecAnalyzerNode [%s]: Pass 1 complete for %s (%d chars)",
            self.node_id, comp_name, len(design_analysis_text),
        )

        # ---- Pass 2: Structured metadata extraction (no screenshot) ----
        pass2_user = PASS2_USER_PROMPT.format(
            design_analysis_text=design_analysis_text,
            sibling_names=sibling_names_str,
            partial_spec_json=partial_spec_json,
        )

        pass2_result = await _invoke_claude_cli(
            claude_bin=claude_bin,
            system_prompt=PASS2_SYSTEM_PROMPT,
            user_prompt=pass2_user,
            base_dir=cwd,  # no screenshot needed for extraction
            model=model,
            timeout=120.0,  # shorter timeout — extraction is simpler
            max_retries=max_retries,
            component_name=f"{comp_name}_pass2",
            caller=f"SpecAnalyzerNode [{self.node_id}]",
        )

        total_retries += pass2_result.get("retry_count", 0)
        if pass2_result["token_usage"]:
            total_tokens["input_tokens"] += pass2_result["token_usage"].get("input_tokens", 0)
            total_tokens["output_tokens"] += pass2_result["token_usage"].get("output_tokens", 0)

        # Parse Pass 2 JSON (with sanitize safety net from T134)
        raw_pass2 = pass2_result["text"]
        analyzer_output = _parse_llm_json(
            raw_pass2, caller=f"SpecAnalyzerNode [{self.node_id}] pass2",
        )

        # Retry with error feedback if Pass 2 parse failed
        if not analyzer_output:
            logger.warning(
                "SpecAnalyzerNode [%s]: Pass 2 JSON parse failed for %s, "
                "attempting retry with error feedback",
                self.node_id, comp_name,
            )
            analyzer_output = await self._retry_with_error_feedback(
                claude_bin=claude_bin,
                raw_text=raw_pass2,
                cwd=cwd,
                model=model,
                component_name=f"{comp_name}_pass2",
            )

        if not analyzer_output:
            # Pass 2 failed completely — preserve design_analysis from Pass 1
            # with safe defaults for structured fields
            logger.error(
                "SpecAnalyzerNode [%s]: Pass 2 failed for %s, "
                "using Pass 1 analysis with default structured fields",
                self.node_id, comp_name,
            )
            analyzer_output = {
                "role": "section",  # safe default
                "description": "",
                "suggested_name": comp_name,
            }

        # Inject design_analysis from Pass 1 directly (never serialized as JSON)
        analyzer_output["design_analysis"] = design_analysis_text

        # Merge LLM output into component using spec_merger
        merged = merge_analyzer_output(component, analyzer_output)

        # Attach tracking metadata (both passes combined)
        duration_ms = int((_time.monotonic() - _start_time) * 1000)
        if total_tokens["input_tokens"] > 0 or total_tokens["output_tokens"] > 0:
            merged["_token_usage"] = total_tokens
        merged["_retry_count"] = total_retries
        merged["_duration_ms"] = duration_ms
        return merged
