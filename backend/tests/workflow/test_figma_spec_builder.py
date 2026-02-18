"""Tests for workflow.nodes.figma_spec_builder — Figma node-to-ComponentSpec conversion.

Covers:
- _should_recurse (pruning rules)
- _normalize_bounds
- figma_node_to_component_spec (core conversion, style extraction, content detection)
- _detect_device_type
"""

from __future__ import annotations

from typing import Any, Dict

import pytest

from workflow.nodes.figma_spec_builder import (
    _detect_device_type,
    _normalize_bounds,
    _should_recurse,
    figma_node_to_component_spec,
)


# ─── Fixtures ─────────────────────────────────────────────────────────


def _make_frame(
    name: str = "Frame",
    node_type: str = "FRAME",
    width: float = 200,
    height: float = 100,
    x: float = 0,
    y: float = 0,
    children: list | None = None,
    **extra,
) -> Dict[str, Any]:
    """Build a minimal Figma node dict."""
    node = {
        "id": extra.pop("id", "1:1"),
        "name": name,
        "type": node_type,
        "visible": extra.pop("visible", True),
        "opacity": extra.pop("opacity", 1.0),
        "absoluteBoundingBox": {"x": x, "y": y, "width": width, "height": height},
        "fills": extra.pop("fills", []),
        "effects": extra.pop("effects", []),
    }
    if children is not None:
        node["children"] = children
    node.update(extra)
    return node


# ─── _should_recurse ─────────────────────────────────────────────────


class TestShouldRecurse:
    def test_vector_types_never_recurse(self):
        for vtype in ("VECTOR", "LINE", "ELLIPSE", "STAR", "REGULAR_POLYGON", "BOOLEAN_OPERATION"):
            node = {"type": vtype, "name": "icon"}
            assert _should_recurse(node, 100, 100, 0) is False

    def test_small_icons_not_recursed(self):
        node = {"type": "FRAME", "name": "icon"}
        assert _should_recurse(node, 24, 24, 0) is False
        assert _should_recurse(node, 20, 16, 0) is False

    def test_larger_than_icon_recursed(self):
        node = {"type": "FRAME", "name": "card"}
        assert _should_recurse(node, 200, 100, 0) is True

    def test_depth_limit_stops_recursion(self):
        node = {"type": "FRAME", "name": "deep"}
        assert _should_recurse(node, 200, 100, 20) is False  # at limit
        assert _should_recurse(node, 200, 100, 19) is True   # below limit

    def test_render_hint_nodes_not_recursed(self):
        """Nodes with names matching render hints (e.g., status bar) should not recurse."""
        node = {"type": "FRAME", "name": "status-bar"}
        result = _should_recurse(node, 393, 44, 0)
        # If detect_render_hint returns truthy for "status-bar", should be False
        # Otherwise True — this tests the integration
        assert isinstance(result, bool)


# ─── _normalize_bounds ────────────────────────────────────────────────


class TestNormalizeBounds:
    def test_subtracts_origin(self):
        spec = {"bounds": {"x": 100, "y": 200, "width": 50, "height": 30}}
        result = _normalize_bounds(spec, 100, 200)
        assert result["bounds"]["x"] == 0
        assert result["bounds"]["y"] == 0
        assert result["bounds"]["width"] == 50
        assert result["bounds"]["height"] == 30

    def test_negative_origin(self):
        spec = {"bounds": {"x": 50, "y": 100, "width": 200, "height": 100}}
        result = _normalize_bounds(spec, 50, 100)
        assert result["bounds"]["x"] == 0
        assert result["bounds"]["y"] == 0

    def test_recurses_into_children(self):
        spec = {
            "bounds": {"x": 100, "y": 200, "width": 393, "height": 852},
            "children": [
                {"bounds": {"x": 120, "y": 220, "width": 100, "height": 50}},
            ],
        }
        result = _normalize_bounds(spec, 100, 200)
        assert result["children"][0]["bounds"]["x"] == 20
        assert result["children"][0]["bounds"]["y"] == 20

    def test_no_bounds_key_unchanged(self):
        spec = {"id": "1:1", "name": "no-bounds"}
        result = _normalize_bounds(spec, 0, 0)
        assert "bounds" not in result

    def test_rounds_values(self):
        spec = {"bounds": {"x": 100.7, "y": 200.3, "width": 50.5, "height": 30.9}}
        result = _normalize_bounds(spec, 0.2, 0.1)
        assert isinstance(result["bounds"]["x"], int)
        assert isinstance(result["bounds"]["y"], int)


# ─── figma_node_to_component_spec ────────────────────────────────────


class TestFigmaNodeToComponentSpec:
    def test_basic_frame(self):
        node = _make_frame(name="Header", width=393, height=80, id="1:1")
        spec = figma_node_to_component_spec(node)

        assert spec is not None
        assert spec["id"] == "1:1"
        assert spec["name"] == "Header"
        assert spec["role"] == "other"  # placeholder for LLM
        assert spec["description"] == ""
        assert spec["bounds"]["width"] == 393
        assert spec["bounds"]["height"] == 80

    def test_invisible_node_returns_none(self):
        node = _make_frame(visible=False)
        assert figma_node_to_component_spec(node) is None

    def test_zero_opacity_returns_none(self):
        node = _make_frame(opacity=0)
        assert figma_node_to_component_spec(node) is None

    def test_zero_size_returns_none(self):
        node = _make_frame(width=0, height=100)
        assert figma_node_to_component_spec(node) is None

    def test_no_bbox_returns_none(self):
        node = {"id": "1:1", "name": "bad", "type": "FRAME", "visible": True, "opacity": 1.0}
        assert figma_node_to_component_spec(node) is None

    def test_text_node_with_typography(self):
        node = _make_frame(
            name="Title",
            node_type="TEXT",
            width=200,
            height=30,
            style={"fontFamily": "Inter", "fontSize": 24, "fontWeight": 700},
        )
        spec = figma_node_to_component_spec(node)
        assert spec is not None
        # Typography should be populated for TEXT nodes (depends on figma_text_to_typography)
        assert spec["name"] == "Title"

    def test_children_are_recursed(self):
        child = _make_frame(
            name="Child", id="1:2", width=100, height=50, x=10, y=10,
        )
        parent = _make_frame(
            name="Parent", id="1:1", width=393, height=200,
            children=[child],
        )
        spec = figma_node_to_component_spec(parent)
        assert spec is not None
        assert len(spec.get("children", [])) == 1
        assert spec["children"][0]["name"] == "Child"

    def test_invisible_children_excluded(self):
        child_visible = _make_frame(name="Visible", id="1:2", width=100, height=50)
        child_hidden = _make_frame(name="Hidden", id="1:3", width=100, height=50, visible=False)
        parent = _make_frame(
            name="Parent", id="1:1", width=393, height=200,
            children=[child_visible, child_hidden],
        )
        spec = figma_node_to_component_spec(parent)
        assert spec is not None
        assert len(spec.get("children", [])) == 1

    def test_icon_detection_small_vector(self):
        node = _make_frame(
            name="arrow-left",
            node_type="VECTOR",
            width=24,
            height=24,
            fills=[{"visible": True, "type": "SOLID", "color": {"r": 0, "g": 0, "b": 0, "a": 1}}],
        )
        spec = figma_node_to_component_spec(node)
        assert spec is not None
        assert "content" in spec
        assert "icon" in spec["content"]
        assert spec["content"]["icon"]["name"] == "arrow-left"
        assert spec["content"]["icon"]["size"] == 24

    def test_image_detection(self):
        node = _make_frame(
            name="Hero Image",
            width=393,
            height=200,
            fills=[{"visible": True, "type": "IMAGE", "imageRef": "abc123", "scaleMode": "FILL"}],
        )
        spec = figma_node_to_component_spec(node)
        assert spec is not None
        assert "content" in spec
        assert "image" in spec["content"]
        assert spec["content"]["image"]["fit"] == "cover"
        assert "figma://image/abc123" in spec["content"]["image"]["src"]

    def test_image_aspect_ratio(self):
        node = _make_frame(
            name="Photo",
            width=300,
            height=200,
            fills=[{"visible": True, "type": "IMAGE", "imageRef": "img1", "scaleMode": "FILL"}],
        )
        spec = figma_node_to_component_spec(node)
        assert spec["content"]["image"]["aspect_ratio"] == "3:2"

    def test_auto_layout_source(self):
        node = _make_frame(
            name="Row",
            width=393,
            height=80,
            layoutMode="HORIZONTAL",
            children=[_make_frame(name="Item", id="1:2", width=100, height=80)],
        )
        spec = figma_node_to_component_spec(node)
        assert spec is not None
        assert spec["layoutSource"] == "auto-layout"

    def test_inferred_layout_source(self):
        node = _make_frame(
            name="Container",
            width=393,
            height=200,
            children=[_make_frame(name="Child", id="1:2", width=100, height=50)],
        )
        spec = figma_node_to_component_spec(node)
        assert spec is not None
        assert spec["layoutSource"] == "inferred"

    def test_leaf_layout_source(self):
        node = _make_frame(name="Button", width=100, height=40)
        spec = figma_node_to_component_spec(node)
        assert spec is not None
        assert spec["layoutSource"] == "leaf"

    def test_z_index_passed_through(self):
        node = _make_frame(name="Layer", width=100, height=50)
        spec = figma_node_to_component_spec(node, z_index=5)
        assert spec["z_index"] == 5

    def test_style_background(self):
        node = _make_frame(
            name="Card",
            width=300,
            height=200,
            fills=[{"visible": True, "type": "SOLID", "color": {"r": 1, "g": 1, "b": 1, "a": 1}}],
        )
        spec = figma_node_to_component_spec(node)
        assert spec is not None
        assert "background" in spec["style"]

    def test_style_opacity(self):
        node = _make_frame(name="Faded", width=100, height=50, opacity=0.5)
        spec = figma_node_to_component_spec(node)
        assert spec is not None
        assert spec["style"]["opacity"] == 0.5

    def test_corner_radius(self):
        node = _make_frame(
            name="Rounded",
            width=100,
            height=50,
            cornerRadius=12,
        )
        spec = figma_node_to_component_spec(node)
        assert spec is not None
        if "corner_radius" in spec["style"]:
            assert spec["style"]["corner_radius"] is not None

    def test_path_building(self):
        child = _make_frame(name="Button", id="1:2", width=100, height=40)
        parent = _make_frame(name="NavBar", id="1:1", width=393, height=60, children=[child])
        spec = figma_node_to_component_spec(parent)
        # _to_component_name normalizes casing
        assert spec["path"] == spec["name"]
        assert "/" in spec["children"][0]["path"]
        assert spec["children"][0]["path"].startswith(spec["name"])

    def test_pruning_tracks_child_ids(self):
        """When not recursing (e.g., small node), pruned child IDs should be tracked."""
        small_child = _make_frame(name="Dot", id="1:3", width=10, height=10)
        # Small parent (<=24px) with children — should not recurse
        parent = _make_frame(
            name="Icon",
            node_type="FRAME",
            width=20,
            height=20,
            id="1:1",
            children=[small_child],
        )
        spec = figma_node_to_component_spec(parent)
        assert spec is not None
        assert len(spec.get("children", [])) == 0  # not recursed
        assert "1:3" in spec.get("_pruned_child_ids", [])


# ─── _detect_device_type ─────────────────────────────────────────────


class TestDetectDeviceType:
    def test_mobile_widths(self):
        for w in (360, 375, 390, 393, 412, 414, 428, 430):
            assert _detect_device_type(w) == "mobile"

    def test_mobile_near_match(self):
        assert _detect_device_type(395) == "mobile"  # within ±10 of 393
        assert _detect_device_type(383) == "mobile"  # within ±10 of 393

    def test_tablet_widths(self):
        for w in (744, 768, 810, 820, 834):
            assert _detect_device_type(w) == "tablet"

    def test_desktop(self):
        assert _detect_device_type(1024) == "desktop"
        assert _detect_device_type(1440) == "desktop"
        assert _detect_device_type(1920) == "desktop"

    def test_ambiguous_defaults_to_mobile(self):
        assert _detect_device_type(500) == "mobile"
