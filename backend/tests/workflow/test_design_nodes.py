"""Smoke tests for Design-to-Code pipeline nodes (M20 L2-L5).

Tests cover:
- L2: Registry helpers, component normalization, spatial neighbors, CSS var names,
       component classification, implementation ordering
- L3: Execution flow with mock Claude CLI (DesignAnalyzerNode JSON mode,
       SkeletonGeneratorNode, ComponentGeneratorNode, VisualDiffNode, AssemblerNode)
- L4: State management (registry accumulation, update_key for nested dict)
- L5: Edge cases (empty components, missing screenshots, timeout, invalid JSON)

All AI calls (stream_claude_events) and subprocess calls are mocked.
"""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Import module helpers and node classes
from workflow.nodes.design import (
    DesignAnalyzerNode,
    SkeletonGeneratorNode,
    ComponentGeneratorNode,
    VisualDiffNode,
    AssemblerNode,
    empty_component_registry,
    add_component_to_registry,
    get_neighbor_code,
    get_interface_summary,
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

# Mock CLI outputs from browser-tester's cli-output-reference.json
MOCK_CLI_PASS = json.dumps({
    "component_id": "header",
    "verdict": "pass",
    "pixel_diff": {
        "diffPercentage": 0.35,
        "totalPixels": 36156,
        "diffPixels": 126,
        "diffImagePath": "/tmp/vdiff/diff.png",
    },
    "timestamp": "2026-02-14T08:06:59.471Z",
})

MOCK_CLI_FAIL = json.dumps({
    "component_id": "header-bad",
    "verdict": "fail",
    "pixel_diff": {
        "diffPercentage": 77.67,
        "totalPixels": 36156,
        "diffPixels": 28082,
        "diffImagePath": "/tmp/vdiff/diff.png",
    },
    "timestamp": "2026-02-14T08:07:05.736Z",
})


def _make_component_entry(
    name: str,
    status: str = "completed",
    code: str = "export default function X() { return <div/>; }",
    neighbors: List[str] | None = None,
) -> Dict[str, Any]:
    """Create a mock component entry for the registry."""
    return {
        "name": name,
        "file_path": f"components/{name}.tsx",
        "export_name": name,
        "props_interface": f"interface {name}Props {{ }}",
        "css_variables": [f"--{name.lower()}-bg"],
        "node_id": f"test:{name}",
        "status": status,
        "code": code,
        "neighbors": neighbors or [],
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


class TestComponentRegistry:
    """Test ComponentRegistry state helpers."""

    def test_empty_registry(self):
        reg = empty_component_registry()
        assert reg["components"] == []
        assert reg["tokens"] == {}
        assert reg["skeleton_code"] == ""
        assert reg["total"] == 0
        assert reg["completed"] == 0
        assert reg["failed"] == 0

    def test_add_completed_component(self):
        reg = empty_component_registry()
        comp = _make_component_entry("Button", status="completed")
        reg = add_component_to_registry(reg, comp)

        assert reg["total"] == 1
        assert reg["completed"] == 1
        assert reg["failed"] == 0
        assert reg["components"][0]["name"] == "Button"

    def test_add_failed_component(self):
        reg = empty_component_registry()
        comp = _make_component_entry("BrokenCard", status="failed")
        reg = add_component_to_registry(reg, comp)

        assert reg["total"] == 1
        assert reg["completed"] == 0
        assert reg["failed"] == 1

    def test_add_multiple_components(self):
        reg = empty_component_registry()
        reg = add_component_to_registry(reg, _make_component_entry("A", status="completed"))
        reg = add_component_to_registry(reg, _make_component_entry("B", status="completed"))
        reg = add_component_to_registry(reg, _make_component_entry("C", status="failed"))

        assert reg["total"] == 3
        assert reg["completed"] == 2
        assert reg["failed"] == 1

    def test_immutability(self):
        """Adding a component should not mutate the original registry."""
        reg = empty_component_registry()
        reg2 = add_component_to_registry(reg, _make_component_entry("X"))
        assert reg["total"] == 0
        assert reg2["total"] == 1


class TestGetNeighborCode:
    """Test get_neighbor_code context builder."""

    def test_returns_neighbor_code(self):
        reg = empty_component_registry()
        reg = add_component_to_registry(reg, _make_component_entry("Header", code="<Header/>"))
        reg = add_component_to_registry(reg, _make_component_entry("TabBar", code="<TabBar/>"))

        code = get_neighbor_code(reg, "PhotoGrid", ["Header", "TabBar"])
        assert "<Header/>" in code
        assert "<TabBar/>" in code

    def test_excludes_self(self):
        reg = empty_component_registry()
        reg = add_component_to_registry(reg, _make_component_entry("A", code="codeA"))
        code = get_neighbor_code(reg, "A", ["A"])
        assert code == ""

    def test_excludes_incomplete(self):
        reg = empty_component_registry()
        reg = add_component_to_registry(reg, _make_component_entry("A", status="pending", code="codeA"))
        code = get_neighbor_code(reg, "B", ["A"])
        assert code == ""

    def test_empty_neighbors(self):
        reg = empty_component_registry()
        code = get_neighbor_code(reg, "X", [])
        assert code == ""


class TestGetInterfaceSummary:
    """Test interface summary generation."""

    def test_includes_completed_only(self):
        reg = empty_component_registry()
        reg = add_component_to_registry(reg, _make_component_entry("Done", status="completed"))
        reg = add_component_to_registry(reg, _make_component_entry("Pending", status="pending"))

        summary = get_interface_summary(reg)
        assert "Done" in summary
        assert "Pending" not in summary

    def test_empty_registry(self):
        reg = empty_component_registry()
        assert get_interface_summary(reg) == ""


# ============================================================================
# L2: DesignAnalyzerNode pure-function tests
# ============================================================================


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

            # Registry should be initialized with tokens
            assert result["component_registry"]["tokens"] == result["tokens"]
            assert result["component_registry"]["components"] == []

            # current_component_index starts at 0
            assert result["current_component_index"] == 0

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


class TestSkeletonGeneratorNode:
    """Test SkeletonGeneratorNode with mocked Claude CLI."""

    @pytest.mark.asyncio
    @patch("workflow.nodes.agents.stream_claude_events", new_callable=AsyncMock)
    @patch("workflow.nodes.agents._make_sse_event_callback")
    async def test_generates_skeleton(self, mock_callback, mock_stream):
        mock_stream.return_value = {"result": "<div className='flex flex-col'>{children}</div>", "exit_code": 0}
        mock_callback.return_value = MagicMock()

        node = _make_node(SkeletonGeneratorNode, config={
            "prompt_template": "Generate skeleton for: {skeleton_structure}\nTokens: {tokens}\nFramework: {framework}",
            "cwd": "/tmp",
            "framework": "react-tailwind",
        })

        result = await node.execute({
            "skeleton_structure": {"layout": "vertical", "width": 393, "height": 852},
            "tokens": {"colors": {"bg": "#FFF"}},
        })

        assert result["success"] is True
        assert "flex flex-col" in result["skeleton_code"]
        # Should update component_registry
        assert result["component_registry"]["skeleton_code"] == result["skeleton_code"]

        # Verify prompt was rendered with placeholders
        call_args = mock_stream.call_args
        prompt = call_args.kwargs.get("prompt") or call_args[1].get("prompt") or call_args[0][0]
        assert "vertical" in prompt
        assert "react-tailwind" in prompt

    @pytest.mark.asyncio
    @patch("workflow.nodes.agents.stream_claude_events", new_callable=AsyncMock)
    @patch("workflow.nodes.agents._make_sse_event_callback")
    async def test_handles_empty_result(self, mock_callback, mock_stream):
        mock_stream.return_value = {"result": "", "exit_code": 1}
        mock_callback.return_value = MagicMock()

        node = _make_node(SkeletonGeneratorNode, config={
            "prompt_template": "test",
            "cwd": "/tmp",
        })

        result = await node.execute({"skeleton_structure": {}, "tokens": {}})
        assert result["success"] is False
        assert result["skeleton_code"] == ""


class TestComponentGeneratorNode:
    """Test ComponentGeneratorNode loop execution."""

    @pytest.mark.asyncio
    @patch("workflow.nodes.agents.stream_claude_events", new_callable=AsyncMock)
    @patch("workflow.nodes.agents._make_sse_event_callback")
    async def test_generates_component(self, mock_callback, mock_stream):
        mock_stream.return_value = {"result": "export default function Header() { return <header/>; }", "exit_code": 0}
        mock_callback.return_value = MagicMock()

        node = _make_node(ComponentGeneratorNode, config={
            "prompt_template": "Generate {component_name} ({component_type}) using {framework}. Tokens: {tokens}. Skeleton: {skeleton}. Summary: {interface_summary}. Neighbors: {neighbor_code}.",
            "cwd": "/tmp",
            "framework": "react-tailwind",
        })

        registry = empty_component_registry()
        registry["tokens"] = {"colors": {"bg": "#FFF"}}
        registry["skeleton_code"] = "<div/>"

        result = await node.execute({
            "component_list": [
                {"name": "Header", "type": "organism", "node_id": "1:10", "neighbors": []},
                {"name": "TabBar", "type": "molecule", "node_id": "1:20", "neighbors": ["Header"]},
            ],
            "current_component_index": 0,
            "component_registry": registry,
        })

        assert result["success"] is True
        assert "Header" in result["code"]
        assert result["component_name"] == "Header"
        assert result["component_index"] == 0
        assert result["file_path"] == "components/Header.tsx"

    @pytest.mark.asyncio
    @patch("workflow.nodes.agents.stream_claude_events", new_callable=AsyncMock)
    @patch("workflow.nodes.agents._make_sse_event_callback")
    async def test_second_component_with_neighbor_context(self, mock_callback, mock_stream):
        """When generating component 2, neighbor code from component 1 should be included."""
        mock_stream.return_value = {"result": "export default function TabBar() { return <nav/>; }", "exit_code": 0}
        mock_callback.return_value = MagicMock()

        node = _make_node(ComponentGeneratorNode, config={
            "prompt_template": "Neighbors: {neighbor_code}",
            "cwd": "/tmp",
        })

        registry = empty_component_registry()
        registry = add_component_to_registry(registry, _make_component_entry("Header", code="<header>header code</header>"))

        result = await node.execute({
            "component_list": [
                {"name": "Header", "type": "organism", "node_id": "1:10", "neighbors": []},
                {"name": "TabBar", "type": "molecule", "node_id": "1:20", "neighbors": ["Header"]},
            ],
            "current_component_index": 1,
            "component_registry": registry,
        })

        # Verify prompt included neighbor code
        call_args = mock_stream.call_args
        prompt = call_args.kwargs.get("prompt") or call_args[1].get("prompt") or call_args[0][0]
        assert "header code" in prompt

    @pytest.mark.asyncio
    async def test_index_out_of_bounds(self):
        """Returns failure when index exceeds component list."""
        node = _make_node(ComponentGeneratorNode, config={
            "prompt_template": "test",
            "cwd": "/tmp",
        })
        result = await node.execute({
            "component_list": [{"name": "A"}],
            "current_component_index": 5,
        })
        assert result["success"] is False


class TestVisualDiffNode:
    """Test VisualDiffNode validation layers."""

    @pytest.mark.asyncio
    async def test_l1_compile_pass(self):
        """L1 compile check passes when tsc returns 0."""
        node = _make_node(VisualDiffNode, config={
            "validation_level": "L1",
            "cwd": "/tmp",
        })

        with patch("asyncio.create_subprocess_shell", new_callable=AsyncMock) as mock_proc:
            proc_mock = AsyncMock()
            proc_mock.communicate.return_value = (b"", b"")
            proc_mock.returncode = 0
            mock_proc.return_value = proc_mock

            result = await node.execute({
                "component_name": "Header",
                "component_index": 0,
            })

            assert result["verified"] is True
            assert "L1 compile passed" in result["message"]

    @pytest.mark.asyncio
    async def test_l1_compile_fail(self):
        """L1 compile failure stops validation."""
        node = _make_node(VisualDiffNode, config={
            "validation_level": "L1L2",
            "cwd": "/tmp",
        })

        with patch("asyncio.create_subprocess_shell", new_callable=AsyncMock) as mock_proc:
            proc_mock = AsyncMock()
            proc_mock.communicate.return_value = (b"error TS2304: Cannot find name 'X'", b"")
            proc_mock.returncode = 1
            mock_proc.return_value = proc_mock

            result = await node.execute({
                "component_name": "Header",
                "component_index": 0,
            })

            assert result["verified"] is False
            assert "L1 compile failed" in result["message"]

    @pytest.mark.asyncio
    async def test_l2_pixel_diff_pass(self):
        """L2 pixel diff below threshold → auto-pass."""
        node = _make_node(VisualDiffNode, config={
            "validation_level": "L1L2",
            "pixel_threshold": 5.0,
            "cwd": "/tmp",
        })

        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f1, \
             tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f2:
            f1.write(b"\x89PNG\r\n")  # Minimal PNG-like content
            f2.write(b"\x89PNG\r\n")
            design_path = f1.name
            actual_path = f2.name

        try:
            # Mock both L1 (compile check) and L2 (pixel diff subprocess)
            compile_proc = AsyncMock()
            compile_proc.communicate.return_value = (b"", b"")
            compile_proc.returncode = 0

            pixel_proc = AsyncMock()
            pixel_proc.communicate.return_value = (MOCK_CLI_PASS.encode(), b"")
            pixel_proc.returncode = 0

            call_count = 0

            async def side_effect(*args, **kwargs):
                nonlocal call_count
                call_count += 1
                if call_count == 1:  # L1 compile
                    return compile_proc
                else:  # L2 pixel diff
                    return pixel_proc

            with patch("asyncio.create_subprocess_shell", side_effect=side_effect):
                result = await node.execute({
                    "component_name": "header",
                    "component_index": 0,
                    "component_list": [{"screenshot_path": design_path}],
                    "actual_screenshot": actual_path,
                })

                assert result["verified"] is True
                assert result["pixel_diff_percent"] == 0.35
                assert "auto-pass" in result["message"]
        finally:
            os.unlink(design_path)
            os.unlink(actual_path)

    @pytest.mark.asyncio
    async def test_l2_pixel_diff_auto_fail(self):
        """L2 pixel diff above AI threshold → auto-fail."""
        node = _make_node(VisualDiffNode, config={
            "validation_level": "L1L2",
            "pixel_threshold": 5.0,
            "ai_threshold": 15.0,
            "cwd": "/tmp",
        })

        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f1, \
             tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f2:
            f1.write(b"\x89PNG\r\n")
            f2.write(b"\x89PNG\r\n")
            design_path = f1.name
            actual_path = f2.name

        try:
            compile_proc = AsyncMock()
            compile_proc.communicate.return_value = (b"", b"")
            compile_proc.returncode = 0

            pixel_proc = AsyncMock()
            pixel_proc.communicate.return_value = (MOCK_CLI_FAIL.encode(), b"")
            pixel_proc.returncode = 0

            call_count = 0

            async def side_effect(*args, **kwargs):
                nonlocal call_count
                call_count += 1
                if call_count == 1:
                    return compile_proc
                else:
                    return pixel_proc

            with patch("asyncio.create_subprocess_shell", side_effect=side_effect):
                result = await node.execute({
                    "component_name": "header-bad",
                    "component_index": 0,
                    "component_list": [{"screenshot_path": design_path}],
                    "actual_screenshot": actual_path,
                })

                assert result["verified"] is False
                assert result["pixel_diff_percent"] == 77.67
                assert "auto-fail" in result["message"]
        finally:
            os.unlink(design_path)
            os.unlink(actual_path)

    @pytest.mark.asyncio
    async def test_missing_design_screenshot(self):
        """Missing design screenshot returns error verdict."""
        node = _make_node(VisualDiffNode, config={
            "validation_level": "L1L2",
            "cwd": "/tmp",
        })

        # Mock L1 compile check pass
        with patch("asyncio.create_subprocess_shell", new_callable=AsyncMock) as mock_proc:
            proc_mock = AsyncMock()
            proc_mock.communicate.return_value = (b"", b"")
            proc_mock.returncode = 0
            mock_proc.return_value = proc_mock

            result = await node.execute({
                "component_name": "test",
                "component_index": 0,
                "component_list": [{"screenshot_path": "/nonexistent/design.png"}],
                "actual_screenshot": "/nonexistent/actual.png",
                "screenshots_dir": "",
            })

            # L2 should report error for missing file
            l2 = result.get("validation_layers", {}).get("L2_pixel", {})
            assert l2.get("verdict") == "error" or result["pixel_diff_percent"] == 100.0


class TestAssemblerNode:
    """Test AssemblerNode assembly logic."""

    @pytest.mark.asyncio
    @patch("workflow.nodes.agents.stream_claude_events", new_callable=AsyncMock)
    @patch("workflow.nodes.agents._make_sse_event_callback")
    async def test_assembles_components(self, mock_callback, mock_stream):
        mock_stream.return_value = {"result": "import Header from './Header';\nexport default function Page() { return <Header/>; }", "exit_code": 0}
        mock_callback.return_value = MagicMock()

        node = _make_node(AssemblerNode, config={
            "prompt_template": "Assemble: {skeleton_code}\nComponents: {component_code}\nTokens: {tokens}\nInterfaces: {interface_summary}",
            "cwd": "/tmp",
            "timeout": 60,
        })

        registry = empty_component_registry()
        registry["skeleton_code"] = "<div>{slots}</div>"
        registry = add_component_to_registry(registry, _make_component_entry("Header"))

        # Mock the build check
        with patch.object(node, "_run_build", new_callable=AsyncMock) as mock_build:
            mock_build.return_value = {"passed": True, "output": ""}

            result = await node.execute({"component_registry": registry})

            assert result["success"] is True
            assert result["build_passed"] is True
            assert "Header" in result["assembled_code"]

    @pytest.mark.asyncio
    @patch("workflow.nodes.agents.stream_claude_events", new_callable=AsyncMock)
    @patch("workflow.nodes.agents._make_sse_event_callback")
    async def test_assembly_with_build_failure(self, mock_callback, mock_stream):
        mock_stream.return_value = {"result": "some code", "exit_code": 0}
        mock_callback.return_value = MagicMock()

        node = _make_node(AssemblerNode, config={
            "prompt_template": "{skeleton_code}{component_code}{tokens}{interface_summary}",
            "cwd": "/tmp",
        })

        with patch.object(node, "_run_build", new_callable=AsyncMock) as mock_build:
            mock_build.return_value = {"passed": False, "output": "Build error"}

            result = await node.execute({"component_registry": empty_component_registry()})

            assert result["success"] is True  # Code was generated
            assert result["build_passed"] is False  # But build failed


# ============================================================================
# L4: State management — registry accumulation across loop iterations
# ============================================================================


class TestRegistryAccumulation:
    """Simulate the component loop pattern from design_to_code.json."""

    @pytest.mark.asyncio
    @patch("workflow.nodes.agents.stream_claude_events", new_callable=AsyncMock)
    @patch("workflow.nodes.agents._make_sse_event_callback")
    async def test_component_loop_accumulates_registry(self, mock_callback, mock_stream):
        """Simulate 3 iterations of the component generation loop."""
        component_list = [
            {"name": "Button", "type": "atom", "node_id": "1:1", "neighbors": []},
            {"name": "Card", "type": "molecule", "node_id": "1:2", "neighbors": ["Button"]},
            {"name": "Header", "type": "organism", "node_id": "1:3", "neighbors": ["Card"]},
        ]

        registry = empty_component_registry()
        registry["tokens"] = {"colors": {"bg": "#FFF"}}
        registry["skeleton_code"] = "<div/>"

        mock_callback.return_value = MagicMock()

        for i, comp in enumerate(component_list):
            # Mock Claude generating different code for each component
            mock_stream.return_value = {
                "result": f"export default function {comp['name']}() {{ return <div>{comp['name']}</div>; }}",
                "exit_code": 0,
            }

            node = _make_node(ComponentGeneratorNode, config={
                "prompt_template": "{component_name} {tokens} {skeleton} {interface_summary} {neighbor_code}",
                "cwd": "/tmp",
            })

            result = await node.execute({
                "component_list": component_list,
                "current_component_index": i,
                "component_registry": registry,
            })

            assert result["success"] is True

            # Simulate update_state appending to registry (like design_to_code.json does)
            comp_entry = _make_component_entry(
                comp["name"],
                status="completed",
                code=result["code"],
                neighbors=comp["neighbors"],
            )
            registry = add_component_to_registry(registry, comp_entry)

        # After 3 iterations, registry should have all 3 components
        assert registry["total"] == 3
        assert registry["completed"] == 3
        assert registry["failed"] == 0

        # Interface summary should include all 3
        summary = get_interface_summary(registry)
        assert "Button" in summary
        assert "Card" in summary
        assert "Header" in summary

        # Neighbor code for Header should include Card
        neighbor_code = get_neighbor_code(registry, "Header", ["Card"])
        assert "Card" in neighbor_code


# ============================================================================
# L5: Edge cases
# ============================================================================


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

    @pytest.mark.asyncio
    async def test_compile_check_timeout(self):
        """L1 compile check handles timeout gracefully."""
        node = _make_node(VisualDiffNode, config={"validation_level": "L1", "cwd": "/tmp"})

        with patch("asyncio.create_subprocess_shell", new_callable=AsyncMock) as mock_proc:
            proc_mock = AsyncMock()
            proc_mock.communicate.side_effect = asyncio.TimeoutError()
            mock_proc.return_value = proc_mock

            result = await node.execute({"component_name": "test", "component_index": 0})
            assert result["verified"] is False
            assert "timed out" in result["message"].lower()

    @pytest.mark.asyncio
    async def test_pixel_diff_invalid_json(self):
        """L2 pixel diff handles invalid JSON from CLI."""
        node = _make_node(VisualDiffNode, config={
            "validation_level": "L1L2",
            "cwd": "/tmp",
        })

        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f1, \
             tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f2:
            f1.write(b"\x89PNG\r\n")
            f2.write(b"\x89PNG\r\n")
            design_path = f1.name
            actual_path = f2.name

        try:
            compile_proc = AsyncMock()
            compile_proc.communicate.return_value = (b"", b"")
            compile_proc.returncode = 0

            pixel_proc = AsyncMock()
            pixel_proc.communicate.return_value = (b"NOT JSON AT ALL", b"")
            pixel_proc.returncode = 0

            call_count = 0

            async def side_effect(*args, **kwargs):
                nonlocal call_count
                call_count += 1
                return compile_proc if call_count == 1 else pixel_proc

            with patch("asyncio.create_subprocess_shell", side_effect=side_effect):
                result = await node.execute({
                    "component_name": "test",
                    "component_index": 0,
                    "component_list": [{"screenshot_path": design_path}],
                    "actual_screenshot": actual_path,
                })

                l2 = result.get("validation_layers", {}).get("L2_pixel", {})
                assert l2.get("verdict") == "error"
                assert "JSON" in l2.get("error", "")
        finally:
            os.unlink(design_path)
            os.unlink(actual_path)

    def test_registry_immutability_under_stress(self):
        """Registry stays immutable across many additions."""
        reg = empty_component_registry()
        snapshots = [reg]

        for i in range(10):
            reg = add_component_to_registry(
                reg, _make_component_entry(f"Comp{i}", status="completed")
            )
            snapshots.append(reg)

        # Each snapshot should have exactly i components
        for i, snap in enumerate(snapshots):
            assert snap["total"] == i


# ============================================================================
# L1: Node registration verification
# ============================================================================


class TestDesignNodeRegistration:
    """Verify all 5 design node types are registered correctly."""

    def test_design_analyzer_registered(self):
        from workflow.nodes.registry import is_node_type_registered
        assert is_node_type_registered("design_analyzer")

    def test_skeleton_generator_registered(self):
        from workflow.nodes.registry import is_node_type_registered
        assert is_node_type_registered("skeleton_generator")

    def test_component_generator_registered(self):
        from workflow.nodes.registry import is_node_type_registered
        assert is_node_type_registered("component_generator")

    def test_visual_diff_registered(self):
        from workflow.nodes.registry import is_node_type_registered
        assert is_node_type_registered("visual_diff")

    def test_assembler_registered(self):
        from workflow.nodes.registry import is_node_type_registered
        assert is_node_type_registered("assembler")

    def test_create_design_analyzer_node(self):
        node = create_node("analyzer_1", "design_analyzer", {})
        assert isinstance(node, DesignAnalyzerNode)

    def test_total_registered_types(self):
        """After importing design nodes, should have 14 total types."""
        from workflow.nodes.registry import list_node_types
        types = list_node_types()
        # 9 base + 5 design = 14
        assert len(types) >= 14, f"Expected >= 14 types, got {len(types)}: {types}"
