"""Smoke tests for Design-to-Spec pipeline nodes.

Tests cover:
- L2: Registry helpers, component normalization, spatial neighbors, CSS var names,
       component classification, implementation ordering
- L3: Execution flow (DesignAnalyzerNode JSON mode)
- L5: Edge cases (empty components, missing data)

All AI calls (stream_claude_events) and subprocess calls are mocked.
"""

from __future__ import annotations

import json
import os
import tempfile
from typing import Any, Dict

import pytest

# Import module helpers and node classes
from workflow.nodes.design import (
    DesignAnalyzerNode,
    _get_bounds,
)
from workflow.nodes.registry import create_node


# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------

SAMPLE_DESIGN_EXPORT = {
    "version": "1.0",
    "source": "figma",
    "file_key": "test_key",
    "page_name": "TestPage",
    "page_node_id": "1:1",
    "page_bounds": {"x": 0, "y": 0, "width": 393, "height": 852},
    "variables": {
        "Text Color/字体_黑60%": "#666666",
        "Brand-主题色/品牌色 (100%)": "#FFDD4C",
    },
    "design_tokens": {
        "colors": {"brand-primary": "#FFDD4C", "text-primary": "#000000"},
        "fonts": {"family": "PingFang SC", "weights": {"regular": 400}},
        "spacing": {"page-padding": "16px"},
    },
    "components": [
        {
            "node_id": "1:10",
            "name": "Header",
            "type": "organism",
            "bounds": {"x": 0, "y": 0, "width": 393, "height": 92},
            "children_summary": [
                {"name": "StatusBar", "node_id": "1:11", "type": "atom", "bounds": {"x": 0, "y": 0, "width": 393, "height": 54}},
                {"name": "AppTitle", "node_id": "1:12", "type": "atom", "bounds": {"x": 80, "y": 58, "width": 233, "height": 22}},
            ],
            "text_content": ["App Title", "9:41"],
            "neighbors": ["TabBar"],
            "screenshot_path": "screenshots/1_10.png",
            "notes": "Header with status bar and title",
        },
        {
            "node_id": "1:20",
            "name": "TabBar",
            "type": "molecule",
            "bounds": {"x": 0, "y": 92, "width": 393, "height": 38},
            "children_summary": [],
            "text_content": ["Tab1", "Tab2"],
            "neighbors": ["Header", "PhotoGrid"],
            "screenshot_path": "screenshots/1_20.png",
            "notes": "Tab navigation",
        },
        {
            "node_id": "1:30",
            "name": "PhotoGrid",
            "type": "section",
            "bounds": {"x": 0, "y": 130, "width": 393, "height": 600},
            "children_summary": [
                {"name": "Sidebar", "node_id": "1:31", "type": "organism", "bounds": {"x": 0, "y": 0, "width": 45, "height": 600}},
                {"name": "MainView", "node_id": "1:32", "type": "organism", "bounds": {"x": 50, "y": 0, "width": 343, "height": 600}},
            ],
            "text_content": [],
            "neighbors": ["TabBar"],
            "screenshot_path": "",
            "notes": "Photo grid section",
        },
    ],
}



def _make_node(node_class, node_id: str = "test_node", config: Dict | None = None):
    """Create a node instance with minimal config."""
    return node_class(node_id=node_id, node_type="test", config=config or {})


# ============================================================================
# L2: Unit tests for module helpers
# ============================================================================


class TestGetBounds:
    """Test _get_bounds helper for different Figma node formats."""

    def test_absolute_bounding_box(self):
        node = {"absoluteBoundingBox": {"x": 10, "y": 20, "width": 100, "height": 50}}
        assert _get_bounds(node) == {"x": 10, "y": 20, "width": 100, "height": 50}

    def test_bounds_format(self):
        node = {"bounds": {"x": 5, "y": 15, "width": 200, "height": 80}}
        assert _get_bounds(node) == {"x": 5, "y": 15, "width": 200, "height": 80}

    def test_direct_xy_format(self):
        node = {"x": 0, "y": 0, "width": 393, "height": 852}
        assert _get_bounds(node) == {"x": 0, "y": 0, "width": 393, "height": 852}

    def test_empty_node(self):
        assert _get_bounds({}) == {}





class TestCssVarName:
    """Test _to_css_var_name static method."""

    def test_simple_english(self):
        result = DesignAnalyzerNode._to_css_var_name("Text Color/Primary")
        assert result == "text-color-primary"

    def test_chinese_stripping(self):
        result = DesignAnalyzerNode._to_css_var_name("Fill/背景色_搜索")
        assert result == "fill"

    def test_percentage(self):
        result = DesignAnalyzerNode._to_css_var_name("Brand-主题色/品牌色 (100%)")
        # Chinese stripped, % stripped
        assert "100" in result

    def test_all_chinese(self):
        """Fully Chinese name produces short/empty result (with warning)."""
        result = DesignAnalyzerNode._to_css_var_name("字体黑色")
        assert len(result) < 3  # Will trigger warning


class TestComponentClassification:
    """Test _classify_component_type."""

    def test_atom(self):
        assert DesignAnalyzerNode._classify_component_type(
            2, {"width": 50, "height": 30}, 100000
        ) == "atom"

    def test_molecule(self):
        assert DesignAnalyzerNode._classify_component_type(
            5, {"width": 100, "height": 50}, 100000
        ) == "molecule"

    def test_organism(self):
        assert DesignAnalyzerNode._classify_component_type(
            10, {"width": 200, "height": 100}, 100000
        ) == "organism"

    def test_section_large_area(self):
        assert DesignAnalyzerNode._classify_component_type(
            3, {"width": 400, "height": 300}, 400 * 300
        ) == "section"


class TestComponentName:
    """Test _to_component_name."""

    def test_simple(self):
        assert DesignAnalyzerNode._to_component_name("header bar") == "HeaderBar"

    def test_with_separators(self):
        assert DesignAnalyzerNode._to_component_name("nav_item-1") == "NavItem1"

    def test_starts_with_number(self):
        result = DesignAnalyzerNode._to_component_name("1st-panel")
        assert result[0].isalpha()  # Must start with letter

    def test_empty(self):
        assert DesignAnalyzerNode._to_component_name("") == "UnknownComponent"


class TestSpatialNeighbors:
    """Test _compute_spatial_neighbors."""

    def test_precomputed_neighbors_preserved(self):
        node = _make_node(DesignAnalyzerNode)
        components = [
            {"name": "A", "bounds": {"x": 0, "y": 0, "width": 100, "height": 50}, "neighbors": ["B"]},
            {"name": "B", "bounds": {"x": 0, "y": 50, "width": 100, "height": 50}, "neighbors": ["A"]},
        ]
        result = node._compute_spatial_neighbors(components)
        assert result[0]["neighbors"] == ["B"]
        assert result[1]["neighbors"] == ["A"]

    def test_computes_from_bounds(self):
        node = _make_node(DesignAnalyzerNode)
        components = [
            {"name": "A", "bounds": {"x": 0, "y": 0, "width": 100, "height": 50}, "neighbors": []},
            {"name": "B", "bounds": {"x": 0, "y": 55, "width": 100, "height": 50}, "neighbors": []},
            {"name": "C", "bounds": {"x": 0, "y": 500, "width": 100, "height": 50}, "neighbors": []},
        ]
        result = node._compute_spatial_neighbors(components)
        # A and B are within 50px, C is far away
        assert "B" in result[0]["neighbors"]
        assert "C" not in result[0]["neighbors"]
        assert "A" in result[1]["neighbors"]

    def test_are_spatially_adjacent(self):
        node = _make_node(DesignAnalyzerNode)
        a = {"x": 0, "y": 0, "width": 100, "height": 50}
        b = {"x": 0, "y": 60, "width": 100, "height": 50}
        assert node._are_spatially_adjacent(a, b) is True  # 10px gap < 50px threshold

        c = {"x": 0, "y": 200, "width": 100, "height": 50}
        assert node._are_spatially_adjacent(a, c) is False  # 150px gap > 50px


class TestImplementationOrder:
    """Test _sort_by_implementation_order."""

    def test_atoms_first(self):
        node = _make_node(DesignAnalyzerNode)
        components = [
            {"name": "Org", "type": "organism", "reuse_count": 0},
            {"name": "Atom", "type": "atom", "reuse_count": 0},
            {"name": "Section", "type": "section", "reuse_count": 0},
            {"name": "Mol", "type": "molecule", "reuse_count": 0},
        ]
        result = node._sort_by_implementation_order(components)
        names = [c["name"] for c in result]
        assert names == ["Atom", "Mol", "Org", "Section"]

    def test_reusable_first_within_type(self):
        node = _make_node(DesignAnalyzerNode)
        components = [
            {"name": "Button", "type": "atom", "reuse_count": 5},
            {"name": "Icon", "type": "atom", "reuse_count": 0},
        ]
        result = node._sort_by_implementation_order(components)
        assert result[0]["name"] == "Button"  # Higher reuse count first


class TestNormalizePredetected:
    """Test _normalize_predetected_components."""

    def test_normalizes_children_summary(self):
        node = _make_node(DesignAnalyzerNode)
        components = [
            {
                "name": "Header",
                "node_id": "1:10",
                "type": "organism",
                "bounds": {"x": 0, "y": 0, "width": 393, "height": 92},
                "children_summary": [
                    {"name": "StatusBar", "node_id": "1:11", "type": "atom", "bounds": {}},
                ],
                "text_content": ["Title"],
                "neighbors": ["TabBar"],
                "screenshot_path": "screenshots/header.png",
                "notes": "Header component",
            }
        ]
        result = node._normalize_predetected_components(components)

        assert len(result) == 1
        comp = result[0]
        assert comp["name"] == "Header"
        assert comp["node_id"] == "1:10"
        assert comp["type"] == "organism"
        assert comp["children_count"] == 1
        assert comp["children_names"] == ["StatusBar"]
        assert comp["neighbors"] == ["TabBar"]
        assert comp["text_content"] == ["Title"]

    def test_defaults_for_missing_fields(self):
        node = _make_node(DesignAnalyzerNode)
        components = [{"name": "Minimal"}]
        result = node._normalize_predetected_components(components)

        assert result[0]["node_id"] == ""
        assert result[0]["type"] == "molecule"
        assert result[0]["neighbors"] == []
        assert result[0]["children_count"] == 0


# ============================================================================
# L3: Execution flow with mocked Claude CLI
# ============================================================================


class TestDesignAnalyzerJsonMode:
    """Test DesignAnalyzerNode._execute_from_json with real JSON file."""

    @pytest.mark.asyncio
    async def test_loads_design_export_json(self):
        """Full integration: load design_export.json, produce sorted component list."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(SAMPLE_DESIGN_EXPORT, f)
            tmp_path = f.name

        try:
            node = _make_node(DesignAnalyzerNode, config={"cwd": "/tmp"})
            result = await node._execute_from_json(tmp_path, "auto", {})

            # Should have 3 components
            assert result["total_components"] == 3
            assert len(result["components"]) == 3

            # Components should be sorted: atoms/molecules before organisms/sections
            types = [c["type"] for c in result["components"]]
            type_priority = {"atom": 0, "molecule": 1, "organism": 2, "section": 3}
            priorities = [type_priority.get(t, 2) for t in types]
            assert priorities == sorted(priorities), f"Not sorted: {types}"

            # Design tokens should be passed through
            assert result["tokens"]["colors"]["brand-primary"] == "#FFDD4C"

            # Skeleton structure built from components
            skeleton = result["skeleton_structure"]
            assert skeleton["width"] == 393
            assert skeleton["height"] == 852
            assert len(skeleton["sections"]) == 3
        finally:
            os.unlink(tmp_path)

    @pytest.mark.asyncio
    async def test_prefers_design_tokens_over_variables(self):
        """When design_tokens is present, use it instead of parsing variables."""
        data = {**SAMPLE_DESIGN_EXPORT}
        data["design_tokens"] = {"colors": {"custom": "#FF0000"}}

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(data, f)
            tmp_path = f.name

        try:
            node = _make_node(DesignAnalyzerNode, config={"cwd": "/tmp"})
            result = await node._execute_from_json(tmp_path, "auto", {})
            assert result["tokens"] == {"colors": {"custom": "#FF0000"}}
        finally:
            os.unlink(tmp_path)

    @pytest.mark.asyncio
    async def test_falls_back_to_variable_parsing(self):
        """When design_tokens is missing, parse from variables."""
        data = {**SAMPLE_DESIGN_EXPORT}
        del data["design_tokens"]

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(data, f)
            tmp_path = f.name

        try:
            node = _make_node(DesignAnalyzerNode, config={"cwd": "/tmp"})
            result = await node._execute_from_json(tmp_path, "auto", {})
            # Should have parsed variables into tokens
            assert "colors" in result["tokens"]
            assert len(result["tokens"]["colors"]) > 0
        finally:
            os.unlink(tmp_path)

    @pytest.mark.asyncio
    async def test_execute_dispatches_to_json(self):
        """execute() dispatches to _execute_from_json when design_source='json'."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(SAMPLE_DESIGN_EXPORT, f)
            tmp_path = f.name

        try:
            node = _make_node(DesignAnalyzerNode, config={
                "design_source": "json",
                "design_file": tmp_path,
            })
            result = await node.execute({})
            assert result["total_components"] == 3
        finally:
            os.unlink(tmp_path)







class TestEdgeCases:
    """Edge case tests for design nodes."""

    @pytest.mark.asyncio
    async def test_empty_components_list(self):
        """DesignAnalyzerNode with empty components list."""
        data = {**SAMPLE_DESIGN_EXPORT, "components": []}

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(data, f)
            tmp_path = f.name

        try:
            node = _make_node(DesignAnalyzerNode, config={"cwd": "/tmp"})
            result = await node._execute_from_json(tmp_path, "auto", {})
            assert result["total_components"] == 0
            assert result["components"] == []
        finally:
            os.unlink(tmp_path)

    @pytest.mark.asyncio
    async def test_no_components_or_tree_raises(self):
        """DesignAnalyzerNode raises when neither components nor node_tree present."""
        data = {"version": "1.0", "design_tokens": {}}

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(data, f)
            tmp_path = f.name

        try:
            node = _make_node(DesignAnalyzerNode, config={"cwd": "/tmp"})
            with pytest.raises(ValueError, match="must have 'components' or 'node_tree'"):
                await node._execute_from_json(tmp_path, "auto", {})
        finally:
            os.unlink(tmp_path)



# ============================================================================
# L1: Node registration verification
# ============================================================================


class TestDesignNodeRegistration:
    """Verify design_analyzer node type is registered correctly."""

    def test_design_analyzer_registered(self):
        from workflow.nodes.registry import is_node_type_registered
        assert is_node_type_registered("design_analyzer")

    def test_create_design_analyzer_node(self):
        node = create_node("analyzer_1", "design_analyzer", {})
        assert isinstance(node, DesignAnalyzerNode)

    def test_total_registered_types(self):
        """After importing design nodes, should have >= 9 total types."""
        from workflow.nodes.registry import list_node_types
        types = list_node_types()
        # 5 base + 2 agent + 2 state + 1 design + 3 spec = 13
        assert len(types) >= 9, f"Expected >= 9 types, got {len(types)}: {types}"
