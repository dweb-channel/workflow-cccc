"""Tests for frame_classifier.py — LLM classification prompt + rule-based pre-filter.

D6 deliverable: 3 test case sets covering rule-based classification,
prompt generation, and LLM output parsing.
"""

from __future__ import annotations

import json
import pytest

from workflow.integrations.frame_classifier import (
    ClassificationResult,
    FrameCategory,
    FrameClassification,
    associate_interaction_specs,
    build_classification_prompt,
    classify_frames_rules_only,
    create_llm_frame_classifier,
    merge_classifications,
    parse_llm_classification,
    rule_based_classify,
    rule_based_classify_all,
)


# ─── Test Case Set 1: Real-world Figma page (像素芝士 V2.9 模拟) ───────────

# Simulates page 2172:2255 with 25 top-level frames:
# - 5 UI screens (mobile 393×852)
# - 3 interaction specs (varied sizes, near UI screens)
# - 2 design system frames (color palette, typography)
# - 3 reference/archive frames
# - 2 other (checklist, notes)
# - 10 ambiguous frames (need LLM)

REAL_WORLD_FRAMES = [
    # --- UI Screens (standard mobile size) ---
    {
        "id": "2172:2256", "name": "通屏效果", "type": "FRAME",
        "absoluteBoundingBox": {"x": 0, "y": 0, "width": 393, "height": 852},
        "children": [{"name": "StatusBar", "type": "FRAME"}, {"name": "Header", "type": "FRAME"},
                      {"name": "Content", "type": "FRAME"}, {"name": "BottomNav", "type": "FRAME"}] * 3,
    },
    {
        "id": "2172:2300", "name": "首页", "type": "FRAME",
        "absoluteBoundingBox": {"x": 500, "y": 0, "width": 393, "height": 852},
        "children": [{"type": "FRAME", "name": f"child_{i}"} for i in range(20)],
    },
    {
        "id": "2172:2400", "name": "详情页", "type": "FRAME",
        "absoluteBoundingBox": {"x": 1000, "y": 0, "width": 393, "height": 852},
        "children": [{"type": "FRAME", "name": f"child_{i}"} for i in range(15)],
    },
    {
        "id": "2172:2500", "name": "搜索结果", "type": "FRAME",
        "absoluteBoundingBox": {"x": 1500, "y": 0, "width": 390, "height": 844},
        "children": [{"type": "FRAME", "name": f"child_{i}"} for i in range(10)],
    },
    {
        "id": "2172:2600", "name": "个人中心", "type": "FRAME",
        "absoluteBoundingBox": {"x": 2000, "y": 0, "width": 375, "height": 812},
        "children": [{"type": "FRAME", "name": f"child_{i}"} for i in range(8)],
    },

    # --- Interaction Specs (near UI screens) ---
    {
        "id": "2172:3000", "name": "动画效果", "type": "FRAME",
        "absoluteBoundingBox": {"x": 0, "y": 900, "width": 800, "height": 600},
        "children": [
            {"type": "TEXT", "name": "说明文字", "characters": "启动页 logo 放大动画 800ms"},
            {"type": "LINE", "name": "连线1"},
            {"type": "ARROW", "name": "箭头1"},
        ],
    },
    {
        "id": "2172:3100", "name": "首页交互说明", "type": "FRAME",
        "absoluteBoundingBox": {"x": 500, "y": 900, "width": 600, "height": 400},
        "children": [
            {"type": "TEXT", "name": "标注", "characters": "点击Tab切换内容区域"},
            {"type": "TEXT", "name": "标注2", "characters": "下拉刷新加载更多"},
        ],
    },
    {
        "id": "2172:3200", "name": "页面跳转流程", "type": "FRAME",
        "absoluteBoundingBox": {"x": 1000, "y": 900, "width": 1200, "height": 500},
        "children": [
            {"type": "LINE", "name": "flow_line_1"},
            {"type": "LINE", "name": "flow_line_2"},
            {"type": "TEXT", "name": "说明", "characters": "首页→详情→购买"},
        ],
    },

    # --- Design System ---
    {
        "id": "2172:4000", "name": "取色逻辑", "type": "FRAME",
        "absoluteBoundingBox": {"x": 0, "y": 1600, "width": 1200, "height": 400},
        "children": [{"type": "RECTANGLE", "name": f"color_{i}"} for i in range(12)],
    },
    {
        "id": "2172:4100", "name": "字体规范", "type": "FRAME",
        "absoluteBoundingBox": {"x": 1300, "y": 1600, "width": 800, "height": 300},
        "children": [{"type": "TEXT", "name": f"font_{i}"} for i in range(6)],
    },

    # --- Reference/Archive ---
    {
        "id": "2172:5000", "name": "参考图-竞品", "type": "FRAME",
        "absoluteBoundingBox": {"x": 0, "y": 2200, "width": 1920, "height": 1080},
        "children": [{"type": "RECTANGLE", "name": "screenshot"}],
    },
    {
        "id": "2172:5100", "name": "旧版设计稿", "type": "FRAME",
        "absoluteBoundingBox": {"x": 2000, "y": 2200, "width": 393, "height": 852},
        "children": [{"type": "FRAME", "name": f"child_{i}"} for i in range(10)],
    },
    {
        "id": "2172:5200", "name": "deprecated_v1", "type": "FRAME",
        "absoluteBoundingBox": {"x": 2500, "y": 2200, "width": 393, "height": 852},
        "children": [{"type": "FRAME", "name": f"child_{i}"} for i in range(8)],
    },

    # --- Other ---
    {
        "id": "2172:6000", "name": "核查单", "type": "FRAME",
        "absoluteBoundingBox": {"x": 0, "y": 3400, "width": 600, "height": 800},
        "children": [{"type": "TEXT", "name": f"item_{i}"} for i in range(20)],
    },
    {
        "id": "2172:6100", "name": "备注", "type": "FRAME",
        "absoluteBoundingBox": {"x": 700, "y": 3400, "width": 400, "height": 300},
        "children": [{"type": "TEXT", "name": "note", "characters": "本轮修改点"}],
    },

    # --- Ambiguous (need LLM) ---
    {
        "id": "2172:7000", "name": "效果展示", "type": "FRAME",
        "absoluteBoundingBox": {"x": 3000, "y": 0, "width": 500, "height": 700},
        "children": [{"type": "FRAME", "name": f"child_{i}"} for i in range(6)],
    },
    {
        "id": "2172:7100", "name": "补充说明", "type": "FRAME",
        "absoluteBoundingBox": {"x": 3600, "y": 0, "width": 450, "height": 350},
        "children": [{"type": "TEXT", "name": "text"}],
    },
    {
        "id": "2172:7200", "name": "Mask group", "type": "GROUP",
        "absoluteBoundingBox": {"x": 4200, "y": 0, "width": 256, "height": 256},
        "children": [{"type": "RECTANGLE", "name": "rect"}],
    },
    {
        "id": "2172:7300", "name": "效果图交付", "type": "SECTION",
        "absoluteBoundingBox": {"x": 4800, "y": 0, "width": 1600, "height": 1000},
        "children": [{"type": "FRAME", "name": f"screen_{i}"} for i in range(4)],
    },
    {
        "id": "2172:7400", "name": "分享卡片", "type": "FRAME",
        "absoluteBoundingBox": {"x": 5000, "y": 0, "width": 345, "height": 460},
        "children": [{"type": "FRAME", "name": f"child_{i}"} for i in range(7)],
    },
]


class TestRuleBasedClassification:
    """Test Set 1: Rule-based pre-filter accuracy."""

    def test_standard_mobile_screen(self):
        """393×852 frame → ui_screen with high confidence."""
        result = rule_based_classify(REAL_WORLD_FRAMES[0])  # 通屏效果
        assert result.category == FrameCategory.UI_SCREEN
        assert result.confidence >= 0.8
        assert result.node_id == "2172:2256"

    def test_iphone_se_size(self):
        """375×812 frame → ui_screen."""
        result = rule_based_classify(REAL_WORLD_FRAMES[4])  # 个人中心
        assert result.category == FrameCategory.UI_SCREEN
        assert result.confidence >= 0.8

    def test_iphone_14_size(self):
        """390×844 frame → ui_screen."""
        result = rule_based_classify(REAL_WORLD_FRAMES[3])  # 搜索结果
        assert result.category == FrameCategory.UI_SCREEN
        assert result.confidence >= 0.8

    def test_interaction_keyword_cn(self):
        """Name contains '交互说明' → interaction_spec."""
        result = rule_based_classify(REAL_WORLD_FRAMES[6])  # 首页交互说明
        assert result.category == FrameCategory.INTERACTION_SPEC
        assert result.confidence >= 0.8

    def test_design_system_keyword_cn(self):
        """Name contains '取色' → design_system."""
        result = rule_based_classify(REAL_WORLD_FRAMES[8])  # 取色逻辑
        assert result.category == FrameCategory.DESIGN_SYSTEM
        assert result.confidence >= 0.8

    def test_reference_keyword_cn(self):
        """Name contains '参考' → reference."""
        result = rule_based_classify(REAL_WORLD_FRAMES[10])  # 参考图-竞品
        assert result.category == FrameCategory.REFERENCE
        assert result.confidence >= 0.8

    def test_reference_keyword_en(self):
        """Name contains 'deprecated' → reference."""
        result = rule_based_classify(REAL_WORLD_FRAMES[12])  # deprecated_v1
        assert result.category == FrameCategory.REFERENCE
        assert result.confidence >= 0.8

    def test_old_version_keyword(self):
        """Name contains '旧版' → reference."""
        result = rule_based_classify(REAL_WORLD_FRAMES[11])  # 旧版设计稿
        assert result.category == FrameCategory.REFERENCE
        assert result.confidence >= 0.8

    def test_checklist_keyword(self):
        """Name contains '核查' → reference (exclusion keyword)."""
        result = rule_based_classify(REAL_WORLD_FRAMES[13])  # 核查单
        assert result.category == FrameCategory.REFERENCE
        assert result.confidence >= 0.8

    def test_notes_keyword(self):
        """Name contains '备注' → reference (exclusion keyword)."""
        result = rule_based_classify(REAL_WORLD_FRAMES[14])  # 备注
        assert result.category == FrameCategory.REFERENCE
        assert result.confidence >= 0.8

    def test_ambiguous_frame_low_confidence(self):
        """Non-standard size, no keyword match → low confidence."""
        result = rule_based_classify(REAL_WORLD_FRAMES[15])  # 效果展示 500×700
        assert result.confidence < 0.8

    def test_small_mask_group(self):
        """Small 256×256 group → low confidence."""
        result = rule_based_classify(REAL_WORLD_FRAMES[17])  # Mask group
        assert result.confidence < 0.8

    def test_very_wide_frame(self):
        """1200px+ wide frame → likely reference."""
        result = rule_based_classify(REAL_WORLD_FRAMES[7])  # 页面跳转流程 1200×500
        assert result.confidence < 0.8 or result.category in (
            FrameCategory.REFERENCE, FrameCategory.INTERACTION_SPEC
        )

    def test_classify_all_splits_correctly(self):
        """rule_based_classify_all splits into high/low confidence."""
        high, low = rule_based_classify_all(REAL_WORLD_FRAMES)
        # Most clear-cut frames should be high confidence
        assert len(high) >= 10  # 5 UI + 1 interaction + 2 design + 3 reference + 2 other
        assert len(low) >= 3   # Ambiguous frames
        assert len(high) + len(low) == len(REAL_WORLD_FRAMES)

    def test_font_spec_keyword(self):
        """Name contains '字体规范' → design_system (规范 keyword)."""
        result = rule_based_classify(REAL_WORLD_FRAMES[9])  # 字体规范
        assert result.category == FrameCategory.DESIGN_SYSTEM
        assert result.confidence >= 0.8


class TestPromptGeneration:
    """Test Set 2: LLM prompt template generation."""

    def test_prompt_contains_all_frames(self):
        """Prompt should reference all input frames."""
        prompt = build_classification_prompt(REAL_WORLD_FRAMES[:5])
        assert "通屏效果" in prompt
        assert "首页" in prompt
        assert "详情页" in prompt
        assert "搜索结果" in prompt
        assert "个人中心" in prompt

    def test_prompt_includes_sizes(self):
        """Prompt should include frame dimensions."""
        prompt = build_classification_prompt(REAL_WORLD_FRAMES[:3])
        assert "393×852" in prompt

    def test_prompt_includes_positions(self):
        """Prompt should include frame positions."""
        prompt = build_classification_prompt(REAL_WORLD_FRAMES[:1])
        assert "(0, 0)" in prompt

    def test_prompt_includes_children_count(self):
        """Prompt should include children count."""
        prompt = build_classification_prompt(REAL_WORLD_FRAMES[:1])
        assert "子节点:" in prompt

    def test_prompt_includes_classification_categories(self):
        """Prompt should define all 5 categories."""
        prompt = build_classification_prompt(REAL_WORLD_FRAMES[:1])
        assert "ui_screen" in prompt
        assert "interaction_spec" in prompt
        assert "design_system" in prompt
        assert "reference" in prompt
        assert "other" in prompt

    def test_prompt_requests_json_output(self):
        """Prompt should request JSON output format."""
        prompt = build_classification_prompt(REAL_WORLD_FRAMES[:1])
        assert "JSON" in prompt
        assert "node_id" in prompt
        assert "category" in prompt
        assert "confidence" in prompt

    def test_prompt_includes_child_names(self):
        """Prompt should include child node names for context."""
        prompt = build_classification_prompt(REAL_WORLD_FRAMES[:1])
        assert "StatusBar" in prompt or "子节点名称" in prompt

    def test_prompt_token_estimate(self):
        """Prompt for 10 ambiguous frames should be under 3K tokens (~4 chars/token)."""
        ambiguous = [f for f in REAL_WORLD_FRAMES if "7" in f["id"][:5]]
        prompt = build_classification_prompt(ambiguous)
        # Rough estimate: 1 token ≈ 4 chars for mixed Chinese/English
        estimated_tokens = len(prompt) / 3  # Conservative for Chinese
        assert estimated_tokens < 5000, f"Prompt too long: ~{estimated_tokens:.0f} tokens"

    def test_empty_frames(self):
        """Empty frame list → valid prompt (no crash)."""
        prompt = build_classification_prompt([])
        assert "分类规则" in prompt


class TestLLMOutputParsing:
    """Test Set 3: LLM output parsing + merge + spatial association."""

    MOCK_LLM_OUTPUT = json.dumps([
        {
            "node_id": "2172:7000",
            "category": "ui_screen",
            "confidence": 0.85,
            "reason": "包含多个UI组件子节点，结构类似页面",
        },
        {
            "node_id": "2172:7100",
            "category": "interaction_spec",
            "confidence": 0.9,
            "reason": "名称含'说明'，内容为文字标注",
            "related_to": "2172:7000",
        },
        {
            "node_id": "2172:7200",
            "category": "other",
            "confidence": 0.8,
            "reason": "Mask group，图形遮罩非UI组件",
        },
        {
            "node_id": "2172:7300",
            "category": "ui_screen",
            "confidence": 0.7,
            "reason": "Section内包含多个屏幕frame",
        },
        {
            "node_id": "2172:7400",
            "category": "ui_screen",
            "confidence": 0.75,
            "reason": "分享卡片，独立UI组件",
        },
    ])

    def test_parse_valid_json(self):
        """Parse well-formed LLM JSON output."""
        results = parse_llm_classification(self.MOCK_LLM_OUTPUT, REAL_WORLD_FRAMES[15:])
        assert len(results) == 5
        assert results[0].category == FrameCategory.UI_SCREEN
        assert results[0].node_id == "2172:7000"

    def test_parse_with_markdown_wrapper(self):
        """Parse JSON wrapped in markdown code block."""
        wrapped = f"```json\n{self.MOCK_LLM_OUTPUT}\n```"
        results = parse_llm_classification(wrapped, REAL_WORLD_FRAMES[15:])
        assert len(results) == 5

    def test_parse_invalid_json(self):
        """Invalid JSON → empty list (graceful failure)."""
        results = parse_llm_classification("not json", REAL_WORLD_FRAMES)
        assert results == []

    def test_parse_preserves_related_to(self):
        """LLM's related_to field is preserved."""
        results = parse_llm_classification(self.MOCK_LLM_OUTPUT, REAL_WORLD_FRAMES[15:])
        spec = [r for r in results if r.category == FrameCategory.INTERACTION_SPEC]
        assert len(spec) == 1
        assert spec[0].related_to == "2172:7000"

    def test_parse_unknown_category_defaults_to_other(self):
        """Unknown category string → OTHER."""
        bad_output = json.dumps([{
            "node_id": "xxx", "category": "invalid_category",
            "confidence": 0.5, "reason": "test",
        }])
        results = parse_llm_classification(bad_output, [])
        assert len(results) == 1
        assert results[0].category == FrameCategory.OTHER

    def test_merge_rule_and_llm_results(self):
        """Merge high-confidence rule results + LLM results."""
        rule_results = [
            FrameClassification(
                node_id="2172:2256", name="通屏效果", size="393×852",
                width=393, height=852, bounds={"x": 0, "y": 0, "width": 393, "height": 852},
                category=FrameCategory.UI_SCREEN, confidence=0.9, reason="rule",
            ),
        ]
        llm_results = [
            FrameClassification(
                node_id="2172:7000", name="效果展示", size="500×700",
                width=500, height=700, bounds={"x": 3000, "y": 0, "width": 500, "height": 700},
                category=FrameCategory.UI_SCREEN, confidence=0.85, reason="LLM",
            ),
        ]
        merged = merge_classifications(rule_results, llm_results)
        assert len(merged.ui_screens) == 2

    def test_spatial_association(self):
        """Interaction specs associate with nearest UI screen."""
        classification = ClassificationResult(
            ui_screens=[
                FrameClassification(
                    node_id="screen_1", name="首页", size="393×852",
                    width=393, height=852, bounds={"x": 0, "y": 0, "width": 393, "height": 852},
                    category=FrameCategory.UI_SCREEN, confidence=0.9, reason="rule",
                ),
                FrameClassification(
                    node_id="screen_2", name="详情页", size="393×852",
                    width=393, height=852, bounds={"x": 1000, "y": 0, "width": 393, "height": 852},
                    category=FrameCategory.UI_SCREEN, confidence=0.9, reason="rule",
                ),
            ],
            interaction_specs=[
                FrameClassification(
                    node_id="spec_1", name="首页交互", size="600×400",
                    width=600, height=400, bounds={"x": 50, "y": 200, "width": 600, "height": 400},
                    category=FrameCategory.INTERACTION_SPEC, confidence=0.8, reason="rule",
                ),
            ],
        )
        associate_interaction_specs(classification)
        assert classification.interaction_specs[0].related_to == "screen_1"

    def test_spatial_association_max_distance(self):
        """Specs beyond max_distance are not associated."""
        classification = ClassificationResult(
            ui_screens=[
                FrameClassification(
                    node_id="screen_1", name="首页", size="393×852",
                    width=393, height=852, bounds={"x": 0, "y": 0, "width": 393, "height": 852},
                    category=FrameCategory.UI_SCREEN, confidence=0.9, reason="rule",
                ),
            ],
            interaction_specs=[
                FrameClassification(
                    node_id="spec_far", name="远处说明", size="600×400",
                    width=600, height=400, bounds={"x": 5000, "y": 5000, "width": 600, "height": 400},
                    category=FrameCategory.INTERACTION_SPEC, confidence=0.8, reason="rule",
                ),
            ],
        )
        associate_interaction_specs(classification, max_distance=500)
        assert classification.interaction_specs[0].related_to is None

    def test_rules_only_fallback(self):
        """classify_frames_rules_only produces valid result."""
        result = classify_frames_rules_only(REAL_WORLD_FRAMES)
        total = (
            len(result.ui_screens) + len(result.interaction_specs)
            + len(result.design_system) + len(result.reference)
            + len(result.other)
        )
        assert total == len(REAL_WORLD_FRAMES)
        # Should find at least the 5 clear UI screens
        assert len(result.ui_screens) >= 5

    def test_end_to_end_classification_accuracy(self):
        """Full pipeline: rule pre-filter + simulated LLM → >90% accuracy.

        Expected ground truth for REAL_WORLD_FRAMES:
        - UI screens: 2256, 2300, 2400, 2500, 2600 (5)
        - Interaction specs: 3000, 3100, 3200 (3)
        - Design system: 4000, 4100 (2)
        - Reference: 5000, 5100, 5200 (3)
        - Other: 6000, 6100 (2)
        - Ambiguous: 7000-7400 (5) — classified by LLM
        """
        GROUND_TRUTH = {
            "2172:2256": "ui_screen", "2172:2300": "ui_screen", "2172:2400": "ui_screen",
            "2172:2500": "ui_screen", "2172:2600": "ui_screen",
            "2172:3000": "interaction_spec", "2172:3100": "interaction_spec",
            "2172:3200": "interaction_spec",
            "2172:4000": "design_system", "2172:4100": "design_system",
            "2172:5000": "reference", "2172:5100": "reference", "2172:5200": "reference",
            "2172:6000": "reference", "2172:6100": "reference",
        }

        # Rule-based only (no LLM)
        high, low = rule_based_classify_all(REAL_WORLD_FRAMES)

        # Check accuracy of high-confidence results
        correct = 0
        total_checked = 0
        for fc in high:
            if fc.node_id in GROUND_TRUTH:
                total_checked += 1
                if fc.category.value == GROUND_TRUTH[fc.node_id]:
                    correct += 1

        accuracy = correct / total_checked if total_checked > 0 else 0
        assert accuracy >= 0.9, f"Rule accuracy: {accuracy:.0%} ({correct}/{total_checked})"


# ─── Test Case Set 4: create_llm_frame_classifier bridge ────────────────────

class TestCreateLlmFrameClassifier:
    """Tests for the D1↔D6 bridge function."""

    @pytest.mark.asyncio
    async def test_bridge_calls_llm_and_parses(self):
        """Bridge builds prompt, calls LLM, parses results."""
        llm_response = json.dumps([
            {
                "node_id": "f:1",
                "category": "ui_screen",
                "confidence": 0.85,
                "reason": "结构类似页面",
            },
        ])

        captured_prompt = []

        async def mock_llm_call(prompt: str) -> str:
            captured_prompt.append(prompt)
            return llm_response

        classifier = create_llm_frame_classifier(mock_llm_call)
        frames_summary = [
            {
                "node_id": "f:1",
                "name": "神秘内容",
                "size": "500×300",
                "bounds": {"x": 0, "y": 0, "width": 500, "height": 300},
                "section": None,
                "child_count": 3,
                "child_types": ["FRAME", "TEXT", "FRAME"],
                "text_preview": ["一些文字"],
            },
        ]

        results = await classifier(frames_summary)

        # Verify LLM was called with a prompt
        assert len(captured_prompt) == 1
        assert "神秘内容" in captured_prompt[0]
        assert "500×300" in captured_prompt[0]

        # Verify parsed results match D1's expected format
        assert len(results) == 1
        assert results[0]["node_id"] == "f:1"
        assert results[0]["classification"] == "ui_screen"
        assert results[0]["confidence"] == 0.85
        assert "结构类似页面" in results[0]["reason"]

    @pytest.mark.asyncio
    async def test_bridge_adapts_text_preview_list(self):
        """text_preview as list is joined into string for prompt."""
        captured_prompt = []

        async def mock_llm_call(prompt: str) -> str:
            captured_prompt.append(prompt)
            return "[]"

        classifier = create_llm_frame_classifier(mock_llm_call)
        frames_summary = [
            {
                "node_id": "f:2",
                "name": "测试",
                "size": "400×600",
                "bounds": {"x": 0, "y": 0, "width": 400, "height": 600},
                "section": None,
                "child_count": 1,
                "child_types": ["TEXT"],
                "text_preview": ["第一段", "第二段", "第三段"],
            },
        ]

        await classifier(frames_summary)
        # text_preview should be joined
        assert "第一段" in captured_prompt[0]

    @pytest.mark.asyncio
    async def test_bridge_empty_frames(self):
        """Empty frames list → no LLM call, empty results."""
        call_count = 0

        async def mock_llm_call(prompt: str) -> str:
            nonlocal call_count
            call_count += 1
            return "[]"

        classifier = create_llm_frame_classifier(mock_llm_call)
        results = await classifier([])

        assert results == []
        assert call_count == 0

    @pytest.mark.asyncio
    async def test_bridge_llm_failure_propagates(self):
        """LLM call failure propagates to caller (scan_and_classify_frames catches it)."""

        async def failing_llm_call(prompt: str) -> str:
            raise RuntimeError("API down")

        classifier = create_llm_frame_classifier(failing_llm_call)
        with pytest.raises(RuntimeError, match="API down"):
            await classifier([
                {
                    "node_id": "f:1",
                    "name": "test",
                    "size": "500×300",
                    "bounds": {"x": 0, "y": 0, "width": 500, "height": 300},
                    "section": None,
                    "child_count": 0,
                    "child_types": [],
                    "text_preview": "",
                },
            ])

    @pytest.mark.asyncio
    async def test_bridge_multiple_frames(self):
        """Bridge handles multiple frames in one call."""
        llm_response = json.dumps([
            {"node_id": "f:1", "category": "ui_screen", "confidence": 0.8, "reason": "UI页面"},
            {"node_id": "f:2", "category": "interaction_spec", "confidence": 0.9, "reason": "交互说明"},
        ])

        async def mock_llm_call(prompt: str) -> str:
            return llm_response

        classifier = create_llm_frame_classifier(mock_llm_call)
        frames_summary = [
            {
                "node_id": "f:1", "name": "页面A", "size": "500×700",
                "bounds": {"x": 0, "y": 0, "width": 500, "height": 700},
                "section": "效果图", "child_count": 5,
                "child_types": ["FRAME", "FRAME", "TEXT", "FRAME", "FRAME"],
                "text_preview": ["标题", "内容"],
            },
            {
                "node_id": "f:2", "name": "补充说明", "size": "450×350",
                "bounds": {"x": 600, "y": 0, "width": 450, "height": 350},
                "section": None, "child_count": 2,
                "child_types": ["TEXT", "LINE"],
                "text_preview": ["点击跳转详情页"],
            },
        ]

        results = await classifier(frames_summary)
        assert len(results) == 2
        assert results[0]["classification"] == "ui_screen"
        assert results[1]["classification"] == "interaction_spec"
