"""Tests for workflow.nodes.spec_analyzer — SpecAnalyzerNode two-pass LLM analysis.

Covers:
- _strip_semantic_fields helper
- SpecAnalyzerNode.execute (happy path, claude not found, concurrent analysis)
- SpecAnalyzerNode._analyze_single_component (two-pass flow, Pass 2 failure + retry)
- SpecAnalyzerNode._retry_with_error_feedback
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from workflow.nodes.spec_analyzer import SpecAnalyzerNode, _strip_semantic_fields


# ─── _strip_semantic_fields ───────────────────────────────────────────


class TestStripSemanticFields:
    def test_nulls_role_and_description(self):
        spec = {"id": "1", "role": "button", "description": "A button", "bounds": {"x": 0}}
        result = _strip_semantic_fields(spec)
        assert result["role"] is None
        assert result["description"] is None
        assert result["bounds"] == {"x": 0}
        assert result["id"] == "1"

    def test_nulls_render_hint(self):
        spec = {"id": "1", "render_hint": "spacer"}
        result = _strip_semantic_fields(spec)
        assert result["render_hint"] is None

    def test_nulls_interaction(self):
        spec = {"id": "1", "interaction": {"trigger": "click", "action": "navigate"}}
        result = _strip_semantic_fields(spec)
        assert result["interaction"] is None

    def test_recurses_into_children(self):
        spec = {
            "id": "parent",
            "role": "container",
            "children": [
                {"id": "child-1", "role": "text", "description": "Title"},
                {"id": "child-2", "role": "button", "interaction": {"trigger": "click"}},
            ],
        }
        result = _strip_semantic_fields(spec)
        assert result["role"] is None
        assert result["children"][0]["role"] is None
        assert result["children"][0]["description"] is None
        assert result["children"][1]["interaction"] is None

    def test_preserves_structural_fields(self):
        spec = {
            "id": "1",
            "name": "Header",
            "bounds": {"x": 0, "y": 0, "width": 393, "height": 80},
            "layout": {"type": "flex", "direction": "row"},
            "style": {"background": "#fff"},
            "role": "navigation",
        }
        result = _strip_semantic_fields(spec)
        assert result["name"] == "Header"
        assert result["bounds"]["width"] == 393
        assert result["layout"]["type"] == "flex"
        assert result["style"]["background"] == "#fff"

    def test_does_not_mutate_input(self):
        spec = {"id": "1", "role": "button"}
        original_role = spec["role"]
        _strip_semantic_fields(spec)
        assert spec["role"] == original_role

    def test_handles_non_dict_children(self):
        spec = {
            "id": "1",
            "role": "list",
            "children": ["string_item", {"id": "2", "role": "text"}],
        }
        result = _strip_semantic_fields(spec)
        assert result["children"][0] == "string_item"
        assert result["children"][1]["role"] is None


# ─── SpecAnalyzerNode.execute ─────────────────────────────────────────


def _make_node(**config_overrides) -> SpecAnalyzerNode:
    """Create a SpecAnalyzerNode with default test config."""
    config = {"cwd": "/tmp", "model": "", "max_tokens": 4096, "max_retries": 2}
    config.update(config_overrides)
    return SpecAnalyzerNode(
        node_id="spec_analyzer_test",
        node_type="spec_analyzer",
        config=config,
    )


def _make_inputs(components=None):
    """Create default inputs dict for SpecAnalyzerNode.execute."""
    if components is None:
        components = [
            {
                "id": "1:1", "name": "Header", "role": "other",
                "bounds": {"x": 0, "y": 0, "width": 393, "height": 80},
                "screenshot_path": "/tmp/header.png",
            },
        ]
    return {
        "components": components,
        "page": {
            "device": {"type": "mobile", "width": 393, "height": 852},
            "layout": {"type": "flex"},
            "responsive_strategy": "fixed-width",
        },
        "design_tokens": {},
        "source": {"file_key": "abc123"},
        "run_id": "test-run",
    }


class TestSpecAnalyzerNodeExecute:
    @pytest.mark.asyncio
    @patch("shutil.which", return_value=None)
    async def test_claude_not_found_returns_error(self, mock_which):
        """Should return error stats when claude CLI is not in PATH."""
        node = _make_node()
        result = await node.execute(_make_inputs())

        assert "error" in result["analysis_stats"]
        assert "claude" in result["analysis_stats"]["error"].lower()

    @pytest.mark.asyncio
    @patch("shutil.which", return_value="/usr/bin/claude")
    @patch("workflow.nodes.spec_analyzer._invoke_claude_cli", new_callable=AsyncMock)
    @patch("workflow.nodes.spec_analyzer._parse_llm_json")
    @patch("workflow.sse.push_sse_event", new_callable=AsyncMock)
    async def test_happy_path_single_component(
        self, mock_sse, mock_parse, mock_cli, mock_which,
    ):
        """Single component analysis — two passes, merge, SSE push."""
        # Pass 1: free-form text
        mock_cli.side_effect = [
            {
                "text": "This is a navigation header with logo and menu.",
                "token_usage": {"input_tokens": 500, "output_tokens": 200},
                "retry_count": 0,
            },
            # Pass 2: structured JSON
            {
                "text": '{"role": "navigation", "suggested_name": "AppHeader"}',
                "token_usage": {"input_tokens": 300, "output_tokens": 100},
                "retry_count": 0,
            },
        ]
        mock_parse.return_value = {
            "role": "navigation",
            "suggested_name": "AppHeader",
        }

        node = _make_node()
        result = await node.execute(_make_inputs())

        assert result["analysis_stats"]["succeeded"] == 1
        assert result["analysis_stats"]["failed"] == 0
        assert result["token_usage"]["input_tokens"] == 800
        assert result["token_usage"]["output_tokens"] == 300
        assert len(result["components"]) == 1

        # SSE event should have been pushed
        mock_sse.assert_called_once()
        sse_call = mock_sse.call_args
        assert sse_call[0][1] == "spec_analyzed"

    @pytest.mark.asyncio
    @patch("shutil.which", return_value="/usr/bin/claude")
    @patch("workflow.nodes.spec_analyzer._invoke_claude_cli", new_callable=AsyncMock)
    @patch("workflow.nodes.spec_analyzer._parse_llm_json")
    @patch("workflow.sse.push_sse_event", new_callable=AsyncMock)
    async def test_component_analysis_failure_counted(
        self, mock_sse, mock_parse, mock_cli, mock_which,
    ):
        """When a component's analysis raises, it should be counted as failed."""
        mock_cli.side_effect = RuntimeError("CLI crashed")

        node = _make_node()
        result = await node.execute(_make_inputs())

        assert result["analysis_stats"]["failed"] >= 1
        assert result["components"][0].get("_analysis_failed") is True

    @pytest.mark.asyncio
    @patch("shutil.which", return_value="/usr/bin/claude")
    @patch("workflow.nodes.spec_analyzer._invoke_claude_cli", new_callable=AsyncMock)
    @patch("workflow.nodes.spec_analyzer._parse_llm_json")
    @patch("workflow.sse.push_sse_event", new_callable=AsyncMock)
    async def test_pass2_failure_uses_defaults(
        self, mock_sse, mock_parse, mock_cli, mock_which,
    ):
        """When Pass 2 JSON parse fails, should use safe defaults + Pass 1 text."""
        # Pass 1 succeeds
        mock_cli.side_effect = [
            {
                "text": "Design analysis text from Pass 1",
                "token_usage": {"input_tokens": 500, "output_tokens": 200},
                "retry_count": 0,
            },
            # Pass 2 returns unparseable
            {
                "text": "not valid json at all",
                "token_usage": {"input_tokens": 100, "output_tokens": 50},
                "retry_count": 0,
            },
            # Retry also fails
            {
                "text": "still not json",
                "token_usage": None,
                "retry_count": 0,
            },
        ]
        mock_parse.return_value = None  # JSON parse always fails

        node = _make_node()
        result = await node.execute(_make_inputs())

        assert result["analysis_stats"]["succeeded"] == 1
        comp = result["components"][0]
        # Should have design_analysis from Pass 1
        assert comp.get("design_analysis") == "Design analysis text from Pass 1"
        # Should have safe default role
        assert comp.get("role") in ("section", "other")

    @pytest.mark.asyncio
    @patch("shutil.which", return_value="/usr/bin/claude")
    @patch("workflow.nodes.spec_analyzer._invoke_claude_cli", new_callable=AsyncMock)
    @patch("workflow.nodes.spec_analyzer._parse_llm_json")
    @patch("workflow.sse.push_sse_event", new_callable=AsyncMock)
    async def test_multiple_components_concurrent(
        self, mock_sse, mock_parse, mock_cli, mock_which,
    ):
        """Multiple components should be analyzed concurrently."""
        call_count = 0

        async def mock_invoke(**kwargs):
            nonlocal call_count
            call_count += 1
            return {
                "text": f"Analysis {call_count}",
                "token_usage": {"input_tokens": 100, "output_tokens": 50},
                "retry_count": 0,
            }

        mock_cli.side_effect = mock_invoke
        mock_parse.return_value = {"role": "section", "suggested_name": "Comp"}

        components = [
            {"id": f"1:{i}", "name": f"Comp{i}", "role": "other",
             "bounds": {"x": 0, "y": i * 100, "width": 393, "height": 100}}
            for i in range(3)
        ]

        node = _make_node()
        result = await node.execute(_make_inputs(components=components))

        assert result["analysis_stats"]["total"] == 3
        assert result["analysis_stats"]["succeeded"] == 3
        assert len(result["components"]) == 3


# ─── _retry_with_error_feedback ───────────────────────────────────────


class TestRetryWithErrorFeedback:
    @pytest.mark.asyncio
    @patch("workflow.nodes.spec_analyzer._invoke_claude_cli", new_callable=AsyncMock)
    @patch("workflow.nodes.spec_analyzer._parse_llm_json")
    async def test_successful_retry(self, mock_parse, mock_cli):
        """Retry should return corrected JSON when CLI produces valid output."""
        mock_cli.return_value = {
            "text": '{"role": "button"}',
            "token_usage": None,
            "retry_count": 0,
        }
        mock_parse.return_value = {"role": "button"}

        node = _make_node()
        result = await node._retry_with_error_feedback(
            claude_bin="/usr/bin/claude",
            raw_text="{invalid json",
            cwd="/tmp",
            model="",
            component_name="test_comp",
        )

        assert result == {"role": "button"}

    @pytest.mark.asyncio
    @patch("workflow.nodes.spec_analyzer._invoke_claude_cli", new_callable=AsyncMock)
    @patch("workflow.nodes.spec_analyzer._parse_llm_json")
    async def test_retry_failure_returns_none(self, mock_parse, mock_cli):
        """When retry also fails, should return None."""
        mock_cli.side_effect = RuntimeError("CLI failed")

        node = _make_node()
        result = await node._retry_with_error_feedback(
            claude_bin="/usr/bin/claude",
            raw_text="{invalid",
            cwd="/tmp",
            model="",
            component_name="test_comp",
        )

        assert result is None

    @pytest.mark.asyncio
    @patch("workflow.nodes.spec_analyzer._invoke_claude_cli", new_callable=AsyncMock)
    @patch("workflow.nodes.spec_analyzer._parse_llm_json")
    async def test_truncates_long_raw_text(self, mock_parse, mock_cli):
        """Should truncate raw text to 3000 chars in the correction prompt."""
        mock_cli.return_value = {
            "text": '{"role": "text"}',
            "token_usage": None,
            "retry_count": 0,
        }
        mock_parse.return_value = {"role": "text"}

        node = _make_node()
        long_text = "x" * 5000
        await node._retry_with_error_feedback(
            claude_bin="/usr/bin/claude",
            raw_text=long_text,
            cwd="/tmp",
            model="",
            component_name="test_comp",
        )

        # Verify the prompt sent to CLI has truncated text
        call_kwargs = mock_cli.call_args[1]
        assert len(call_kwargs["user_prompt"]) < 4000
