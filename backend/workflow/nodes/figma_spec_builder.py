"""Figma node-to-ComponentSpec builder — core conversion + pruning logic.

Converts raw Figma API node trees into PartialComponentSpec dicts,
applying pruning rules and device detection.
"""

import re
from math import gcd
from typing import Any, Dict, List, Optional

import logging

from .figma_utils import (
    detect_container_layout,
    detect_render_hint,
    figma_color_to_hex,
    figma_corner_radius,
    figma_effects_to_style,
    figma_fills_to_background,
    figma_sizing,
    figma_strokes_to_border,
    figma_text_to_typography,
    _to_component_name,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Pruning: control recursion depth for layout-focused spec
# ---------------------------------------------------------------------------

# Max depth for component tree recursion.
# 20 = deep recursion for fine-grained layout spec output
# (was 0 for codegen-oriented skeleton; now expanded for layout spec)
_MAX_COMPONENT_DEPTH = 20

_VECTOR_TYPES = frozenset({
    "VECTOR", "LINE", "ELLIPSE", "STAR",
    "REGULAR_POLYGON", "BOOLEAN_OPERATION",
})


def _should_recurse(node: Dict, width: float, height: float, depth: int) -> bool:
    """Determine if we should recursively expand a node's children.

    Pruning rules for fine-grained layout spec:
    1. Vector/shape nodes -- internal SVG paths irrelevant for layout
    2. Small icons (<=24px) -- leaf nodes, keep node but skip children
    3. Platform/spacer elements -- system UI, skip internals
    4. Depth limit -- safety cap to prevent infinite recursion
    """
    node_type = node.get("type", "")
    name = node.get("name", "")

    # Rule 1: Vector types never have meaningful layout children
    if node_type in _VECTOR_TYPES:
        return False

    # Rule 2: Very small icons (<=24px) -- keep as leaf, don't recurse
    if width <= 24 and height <= 24:
        return False

    # Rule 3: Platform/spacer elements -- system UI internals
    if detect_render_hint(name):
        return False

    # Rule 4: Depth safety cap
    if depth >= _MAX_COMPONENT_DEPTH:
        return False

    return True


def _normalize_bounds(spec: Dict, origin_x: float, origin_y: float) -> Dict:
    """Normalize canvas-absolute bounds to page-relative coordinates.

    Subtracts page origin so (0, 0) = top-left of the page/frame.
    Recurses into children if present.
    """
    if "bounds" in spec:
        b = spec["bounds"]
        spec["bounds"] = {
            "x": round(b["x"] - origin_x),
            "y": round(b["y"] - origin_y),
            "width": round(b.get("width", 0)),
            "height": round(b.get("height", 0)),
        }
    if "children" in spec and isinstance(spec["children"], list):
        spec["children"] = [
            _normalize_bounds(c, origin_x, origin_y) for c in spec["children"]
        ]
    return spec


# ---------------------------------------------------------------------------
# Core: Figma node -> ComponentSpec mapping
# ---------------------------------------------------------------------------


def figma_node_to_component_spec(
    node: Dict,
    z_index: int = 0,
    reverse_map: Optional[Dict[str, str]] = None,
    depth: int = 0,
    parent_path: str = "",
) -> Optional[Dict[str, Any]]:
    """Convert a raw Figma node to a PartialComponentSpec.

    Maps all deterministic fields (70%):
    - id, name, bounds, layout, sizing, style, typography, content
    - render_hint, z_index

    Leaves LLM fields as placeholders:
    - role -> "other"
    - description -> ""
    - interaction -> None

    Pruning: controlled by _should_recurse() and _MAX_COMPONENT_DEPTH.
    When not recursing, children_bounds are still computed from raw Figma
    bbox for accurate layout detection (stack vs absolute).
    """
    node_type = node.get("type", "")
    name = node.get("name", "Unknown")
    node_id = node.get("id", "")
    visible = node.get("visible", True)

    if not visible:
        return None

    # Filter opacity=0 nodes (visible=True but fully transparent)
    opacity = node.get("opacity", 1.0)
    if opacity == 0:
        return None

    bbox = node.get("absoluteBoundingBox", {})
    if not bbox:
        return None

    width = bbox.get("width", 0)
    height = bbox.get("height", 0)
    if width <= 0 or height <= 0:
        return None

    bounds = {
        "x": bbox.get("x", 0),
        "y": bbox.get("y", 0),
        "width": width,
        "height": height,
    }

    # --- Build path ---
    component_name = _to_component_name(name)
    current_path = f"{parent_path}/{component_name}" if parent_path else component_name

    # --- Determine layoutSource ---
    layout_mode = node.get("layoutMode")
    has_children = bool(node.get("children"))
    if layout_mode:
        layout_source = "auto-layout"
    elif has_children:
        layout_source = "inferred"
    else:
        layout_source = "leaf"

    # --- Build children (with pruning) ---
    children_specs: List[Dict] = []
    children = node.get("children", [])
    children_bounds: List[Dict] = []

    if _should_recurse(node, width, height, depth):
        # Recurse into children
        for i, child in enumerate(children):
            child_spec = figma_node_to_component_spec(
                child, z_index=i, reverse_map=reverse_map,
                depth=depth + 1, parent_path=current_path,
            )
            if child_spec:
                children_specs.append(child_spec)
                children_bounds.append(child_spec["bounds"])
    else:
        # Not recursing -- still compute children_bounds from raw Figma bbox
        # so detect_container_layout() can detect stack (overlapping) layout
        for child in children:
            if not child.get("visible", True):
                continue
            if child.get("opacity", 1.0) == 0:
                continue
            c_bbox = child.get("absoluteBoundingBox", {})
            if c_bbox and c_bbox.get("width", 0) > 0 and c_bbox.get("height", 0) > 0:
                children_bounds.append({
                    "x": c_bbox.get("x", 0),
                    "y": c_bbox.get("y", 0),
                    "width": c_bbox.get("width", 0),
                    "height": c_bbox.get("height", 0),
                })

    # --- Layout ---
    layout = detect_container_layout(node, children_bounds)

    # --- Sizing ---
    sizing = figma_sizing(node)

    # --- Style ---
    fills = node.get("fills", [])
    background = figma_fills_to_background(fills)

    border = figma_strokes_to_border(node)
    corner_radius = figma_corner_radius(node)

    effects = node.get("effects", [])
    effects_style = figma_effects_to_style(effects)

    # opacity already read at top of function for the opacity=0 filter
    style: Dict[str, Any] = {"background": background}
    if border:
        style["border"] = border
    if corner_radius is not None:
        style["corner_radius"] = corner_radius
    if effects_style.get("shadow"):
        style["shadow"] = effects_style["shadow"]
    if opacity < 1.0:
        style["opacity"] = opacity
    if effects_style.get("blur"):
        style["blur"] = effects_style["blur"]

    # --- Typography (TEXT nodes only) ---
    typography = figma_text_to_typography(node)

    # --- Content detection ---
    content: Optional[Dict[str, Any]] = None

    # Icon detection: small VECTOR or small INSTANCE (<=48px)
    is_small = width <= 48 and height <= 48
    if node_type == "VECTOR" or (
        node_type in ("INSTANCE", "COMPONENT") and is_small and not children
    ):
        icon_color = None
        visible_fills = [
            f for f in fills if f.get("visible", True) and f.get("type") == "SOLID"
        ]
        if visible_fills:
            icon_color = figma_color_to_hex(visible_fills[0].get("color", {}))
        content = {
            "icon": {
                "name": name.lower().replace(" ", "-"),
                "size": max(width, height),
            }
        }
        if icon_color:
            content["icon"]["color"] = icon_color

    # Image detection: fills with IMAGE type
    image_fills = [
        f for f in fills if f.get("visible", True) and f.get("type") == "IMAGE"
    ]
    if image_fills:
        fill = image_fills[0]
        image_ref = fill.get("imageRef", "")
        scale_mode = fill.get("scaleMode", "FILL")
        fit_map = {
            "FILL": "cover", "FIT": "contain", "CROP": "cover", "TILE": "none",
        }
        content = {
            "image": {
                "src": f"figma://image/{image_ref}" if image_ref else "",
                "alt": "",  # Node 2 fills via vision API
                "fit": fit_map.get(scale_mode, "cover"),
            }
        }
        if width > 0 and height > 0:
            g = gcd(int(width), int(height))
            content["image"]["aspect_ratio"] = f"{int(width) // g}:{int(height) // g}"

    # --- Assemble spec ---
    # component_name already computed above (for path building)

    spec: Dict[str, Any] = {
        "id": node_id,
        "name": component_name,
        "path": current_path,
        "role": "other",        # Node 2 fills
        "description": "",      # Node 2 fills
        "bounds": bounds,
        "layout": layout,
        "layoutSource": layout_source,
        "sizing": sizing,
        "style": style,
        "z_index": z_index,
    }

    # render_hint
    hint = detect_render_hint(name)
    if hint:
        spec["render_hint"] = hint

    # Optional fields
    if typography:
        spec["typography"] = typography
    if content:
        spec["content"] = content
    if children_specs:
        spec["children"] = children_specs

    return spec


# ---------------------------------------------------------------------------
# Device detection (shared)
# ---------------------------------------------------------------------------

_MOBILE_WIDTHS = {360, 375, 390, 393, 412, 414, 428, 430}
_TABLET_WIDTHS = {744, 768, 810, 820, 834}


def _detect_device_type(width: float) -> str:
    """Detect device type from page width."""
    for mw in _MOBILE_WIDTHS:
        if abs(width - mw) <= 10:
            return "mobile"
    for tw in _TABLET_WIDTHS:
        if abs(width - tw) <= 10:
            return "tablet"
    if width >= 1024:
        return "desktop"
    return "mobile"
