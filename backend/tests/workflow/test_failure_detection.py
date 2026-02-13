"""Unit tests for T100: Bilingual failure detection + structured verify parsing.

Tests cover:
- _FAILURE_INDICATORS bilingual matching in LLMAgentNode
- _parse_verify_verdict: structured verdict lines, word-boundary matching, edge cases

All tests use mocks (no real Claude CLI calls).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest


# ---------------------------------------------------------------------------
# 1. _parse_verify_verdict
# ---------------------------------------------------------------------------


class TestParseVerifyVerdict:
    """Test structured verify verdict parsing."""

    def test_structured_verdict_verified(self):
        from workflow.nodes.agents import _parse_verify_verdict

        assert _parse_verify_verdict("VERDICT: VERIFIED\nThe fix looks correct.") is True

    def test_structured_verdict_failed(self):
        from workflow.nodes.agents import _parse_verify_verdict

        assert _parse_verify_verdict("VERDICT: FAILED\nTests are still broken.") is False

    def test_structured_verdict_result_passed(self):
        from workflow.nodes.agents import _parse_verify_verdict

        assert _parse_verify_verdict("Result: PASSED") is True

    def test_structured_verdict_conclusion_rejected(self):
        from workflow.nodes.agents import _parse_verify_verdict

        assert _parse_verify_verdict("Conclusion: REJECTED") is False

    def test_structured_verdict_chinese_pass(self):
        from workflow.nodes.agents import _parse_verify_verdict

        assert _parse_verify_verdict("结论: 通过\n修复正确。") is True

    def test_structured_verdict_chinese_fail(self):
        from workflow.nodes.agents import _parse_verify_verdict

        assert _parse_verify_verdict("结论: 未通过\n测试仍然失败。") is False

    def test_structured_verdict_chinese_colon(self):
        from workflow.nodes.agents import _parse_verify_verdict

        assert _parse_verify_verdict("结果：验证通过") is True

    def test_structured_verdict_chinese_fail_variant(self):
        from workflow.nodes.agents import _parse_verify_verdict

        assert _parse_verify_verdict("判定：验证失败") is False

    def test_word_boundary_verified(self):
        from workflow.nodes.agents import _parse_verify_verdict

        assert _parse_verify_verdict("The fix is VERIFIED and working.") is True

    def test_word_boundary_unverified_no_match(self):
        from workflow.nodes.agents import _parse_verify_verdict

        # "UNVERIFIED" should NOT match as verified
        assert _parse_verify_verdict("The fix is UNVERIFIED.") is False

    def test_word_boundary_not_verified_no_match(self):
        from workflow.nodes.agents import _parse_verify_verdict

        assert _parse_verify_verdict("NOT_VERIFIED: tests failed") is False

    def test_chinese_pass(self):
        from workflow.nodes.agents import _parse_verify_verdict

        assert _parse_verify_verdict("修复验证通过，所有测试正常。") is True

    def test_chinese_fail_override(self):
        from workflow.nodes.agents import _parse_verify_verdict

        # "通过" is present but "未通过" takes priority
        assert _parse_verify_verdict("验证未通过，3 个测试失败。") is False

    def test_explicit_failed_wins(self):
        from workflow.nodes.agents import _parse_verify_verdict

        # Both VERIFIED and FAILED present — FAILED wins
        assert _parse_verify_verdict("Initially looked VERIFIED but FAILED on edge case.") is False

    def test_chinese_fail_keyword(self):
        from workflow.nodes.agents import _parse_verify_verdict

        assert _parse_verify_verdict("测试失败，需要修改。") is False

    def test_ambiguous_defaults_to_false(self):
        from workflow.nodes.agents import _parse_verify_verdict

        # No clear verdict keywords
        assert _parse_verify_verdict("I looked at the code and it seems okay.") is False

    def test_empty_string(self):
        from workflow.nodes.agents import _parse_verify_verdict

        assert _parse_verify_verdict("") is False

    def test_case_insensitive_verdict_line(self):
        from workflow.nodes.agents import _parse_verify_verdict

        assert _parse_verify_verdict("verdict: verified") is True

    def test_case_insensitive_failed(self):
        from workflow.nodes.agents import _parse_verify_verdict

        assert _parse_verify_verdict("The test Failed.") is False


# ---------------------------------------------------------------------------
# 2. Bilingual failure indicators in LLMAgentNode
# ---------------------------------------------------------------------------


class TestBilingualFailureIndicators:
    """Test that failure detection works in both Chinese and English."""

    @patch("workflow.nodes.agents.stream_claude_events", new_callable=AsyncMock)
    async def test_chinese_failure_detected(self, mock_stream):
        from workflow.nodes.agents import LLMAgentNode

        mock_stream.return_value = "## 根因分析\n无法获取 Jira 信息\n## 修改摘要\n无修改"
        node = LLMAgentNode(
            node_id="fix_bug_peer", node_type="llm_agent",
            config={"prompt": "fix {current_bug}", "name": "Fix"},
        )
        result = await node.execute({"current_bug": "TEST-1"})
        assert result["success"] is False

    @patch("workflow.nodes.agents.stream_claude_events", new_callable=AsyncMock)
    async def test_english_failure_no_modifications(self, mock_stream):
        from workflow.nodes.agents import LLMAgentNode

        mock_stream.return_value = "## 根因分析\nCould not reproduce\n## 修改摘要\nNo modifications were made"
        node = LLMAgentNode(
            node_id="fix_bug_peer", node_type="llm_agent",
            config={"prompt": "fix {current_bug}", "name": "Fix"},
        )
        result = await node.execute({"current_bug": "TEST-1"})
        assert result["success"] is False

    @patch("workflow.nodes.agents.stream_claude_events", new_callable=AsyncMock)
    async def test_english_failure_unreachable(self, mock_stream):
        from workflow.nodes.agents import LLMAgentNode

        mock_stream.return_value = "## 根因分析\nThe server is unreachable\n## 修改摘要\nNo fix applied"
        node = LLMAgentNode(
            node_id="fix_bug_peer", node_type="llm_agent",
            config={"prompt": "fix {current_bug}", "name": "Fix"},
        )
        result = await node.execute({"current_bug": "TEST-1"})
        assert result["success"] is False

    @patch("workflow.nodes.agents.stream_claude_events", new_callable=AsyncMock)
    async def test_english_failure_unable_to_access(self, mock_stream):
        from workflow.nodes.agents import LLMAgentNode

        mock_stream.return_value = "## 根因分析\nUnable to access the repository\n## 修改摘要\nNo changes made"
        node = LLMAgentNode(
            node_id="fix_bug_peer", node_type="llm_agent",
            config={"prompt": "fix {current_bug}", "name": "Fix"},
        )
        result = await node.execute({"current_bug": "TEST-1"})
        assert result["success"] is False

    @patch("workflow.nodes.agents.stream_claude_events", new_callable=AsyncMock)
    async def test_english_failure_case_insensitive(self, mock_stream):
        from workflow.nodes.agents import LLMAgentNode

        mock_stream.return_value = "## 根因分析\nISSUE INACCESSIBLE\n## 修改摘要\nCOULD NOT ACCESS the bug tracker"
        node = LLMAgentNode(
            node_id="fix_bug_peer", node_type="llm_agent",
            config={"prompt": "fix {current_bug}", "name": "Fix"},
        )
        result = await node.execute({"current_bug": "TEST-1"})
        assert result["success"] is False

    @patch("workflow.nodes.agents.stream_claude_events", new_callable=AsyncMock)
    async def test_successful_fix_not_flagged(self, mock_stream):
        from workflow.nodes.agents import LLMAgentNode

        mock_stream.return_value = (
            "## 根因分析\nNull pointer in UserService.java\n"
            "## 修改摘要\nAdded null check at line 42\n"
            "## 测试结果\nAll tests passing"
        )
        node = LLMAgentNode(
            node_id="fix_bug_peer", node_type="llm_agent",
            config={"prompt": "fix {current_bug}", "name": "Fix"},
        )
        result = await node.execute({"current_bug": "TEST-1"})
        assert result["success"] is True

    @patch("workflow.nodes.agents.stream_claude_events", new_callable=AsyncMock)
    async def test_error_result_detected(self, mock_stream):
        from workflow.nodes.agents import LLMAgentNode

        mock_stream.return_value = "[Error] Claude CLI timed out"
        node = LLMAgentNode(
            node_id="fix_bug_peer", node_type="llm_agent",
            config={"prompt": "fix {current_bug}", "name": "Fix"},
        )
        result = await node.execute({"current_bug": "TEST-1"})
        assert result["success"] is False


# ---------------------------------------------------------------------------
# 3. VerifyNode uses _parse_verify_verdict
# ---------------------------------------------------------------------------


class TestVerifyNodeParsing:
    """Test that VerifyNode uses the new structured parser."""

    @patch("workflow.nodes.agents.stream_claude_events", new_callable=AsyncMock)
    async def test_verify_structured_verdict(self, mock_stream):
        from workflow.nodes.agents import VerifyNode

        mock_stream.return_value = "I checked the fix.\n\nVERDICT: VERIFIED"
        node = VerifyNode(
            node_id="verify_fix", node_type="verify",
            config={"verify_type": "llm_agent", "name": "Verify"},
        )
        result = await node.execute({"current_bug": "TEST-1"})
        assert result["verified"] is True

    @patch("workflow.nodes.agents.stream_claude_events", new_callable=AsyncMock)
    async def test_verify_unverified_not_matched(self, mock_stream):
        from workflow.nodes.agents import VerifyNode

        mock_stream.return_value = "Status: UNVERIFIED. Tests are failing."
        node = VerifyNode(
            node_id="verify_fix", node_type="verify",
            config={"verify_type": "llm_agent", "name": "Verify"},
        )
        result = await node.execute({"current_bug": "TEST-1"})
        assert result["verified"] is False

    @patch("workflow.nodes.agents.stream_claude_events", new_callable=AsyncMock)
    async def test_verify_chinese_pass(self, mock_stream):
        from workflow.nodes.agents import VerifyNode

        mock_stream.return_value = "修复验证通过，所有测试正常运行。"
        node = VerifyNode(
            node_id="verify_fix", node_type="verify",
            config={"verify_type": "llm_agent", "name": "Verify"},
        )
        result = await node.execute({"current_bug": "TEST-1"})
        assert result["verified"] is True

    @patch("workflow.nodes.agents.stream_claude_events", new_callable=AsyncMock)
    async def test_verify_failed_wins_over_verified(self, mock_stream):
        from workflow.nodes.agents import VerifyNode

        mock_stream.return_value = "The code was VERIFIED to compile but FAILED on runtime tests."
        node = VerifyNode(
            node_id="verify_fix", node_type="verify",
            config={"verify_type": "llm_agent", "name": "Verify"},
        )
        result = await node.execute({"current_bug": "TEST-1"})
        assert result["verified"] is False

    @patch("workflow.nodes.agents.stream_claude_events", new_callable=AsyncMock)
    async def test_verify_ambiguous_defaults_false(self, mock_stream):
        from workflow.nodes.agents import VerifyNode

        mock_stream.return_value = "The code looks reasonable but I'm not sure."
        node = VerifyNode(
            node_id="verify_fix", node_type="verify",
            config={"verify_type": "llm_agent", "name": "Verify"},
        )
        result = await node.execute({"current_bug": "TEST-1"})
        assert result["verified"] is False
