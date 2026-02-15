"""Spec Pipeline Nodes — FrameDecomposer + SpecAssembler

Three-node pipeline for Design → Spec Document generation:
  Node 1: FrameDecomposerNode — Extracts 70% structural data from Figma nodes
  Node 2: SpecAnalyzerNode — LLM fills remaining 30% (role, description, interaction)
  Node 3: SpecAssemblerNode — Assembles final design_spec.json
"""

import json
import logging
import math
import os
import re
from datetime import datetime, timezone
from math import gcd
from typing import Any, Dict, List, Optional

from .registry import BaseNodeImpl, register_node_type

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Color / Token utilities
# ---------------------------------------------------------------------------

_HEX_COLOR_RE = re.compile(r"^#[0-9A-Fa-f]{6,8}$")


def figma_color_to_hex(color: Dict) -> str:
    """Convert Figma RGBA float dict {r,g,b,a} to hex string."""
    r = round(color.get("r", 0) * 255)
    g = round(color.get("g", 0) * 255)
    b = round(color.get("b", 0) * 255)
    a = color.get("a", 1.0)
    hex_rgb = f"#{r:02X}{g:02X}{b:02X}"
    if a < 1.0:
        hex_rgb += f"{round(a * 255):02X}"
    return hex_rgb


def build_token_reverse_map(design_tokens: Dict) -> Dict[str, str]:
    """Build value → token_name reverse lookup dictionary.

    Matches hex colors (first 7 chars, e.g. '#FF6B35') to token names.
    """
    reverse: Dict[str, str] = {}
    colors = design_tokens.get("colors", {})
    for name, hex_val in colors.items():
        if isinstance(hex_val, str) and hex_val.startswith("#"):
            reverse[hex_val.upper()[:7]] = name
    return reverse


def _fuzzy_token_lookup(hex_color: str, reverse_map: Dict[str, str]) -> Optional[str]:
    """Look up a hex color in the token map with +/-1 tolerance per channel.

    Figma stores colors as floats (0-1). Converting to 0-255 int can cause
    +/-1 rounding differences (e.g. 0.21*255=53.55 rounds to 54 vs 53).
    """
    key = hex_color.upper()[:7]
    # Exact match first
    token = reverse_map.get(key)
    if token:
        return token

    # Fuzzy match: try +/-1 for each RGB channel
    if len(key) >= 7:
        r = int(key[1:3], 16)
        g = int(key[3:5], 16)
        b = int(key[5:7], 16)
        for dr in (-1, 0, 1):
            for dg in (-1, 0, 1):
                for db in (-1, 0, 1):
                    if dr == 0 and dg == 0 and db == 0:
                        continue
                    nr = max(0, min(255, r + dr))
                    ng = max(0, min(255, g + dg))
                    nb = max(0, min(255, b + db))
                    candidate = f"#{nr:02X}{ng:02X}{nb:02X}"
                    token = reverse_map.get(candidate)
                    if token:
                        return token
    return None


def apply_token_reverse_map(obj: Any, reverse_map: Dict[str, str]) -> Any:
    """Recursively traverse JSON tree, convert hex colors to ColorValue format.

    - Matching hex -> {"value": "#FF6B35", "token": "brand-primary"}
    - Non-matching hex -> unchanged string "#FF6B35"
    """
    if isinstance(obj, str) and _HEX_COLOR_RE.match(obj):
        token = _fuzzy_token_lookup(obj, reverse_map)
        if token:
            return {"value": obj, "token": token}
        return obj
    elif isinstance(obj, dict):
        return {k: apply_token_reverse_map(v, reverse_map) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [apply_token_reverse_map(item, reverse_map) for item in obj]
    return obj


# ---------------------------------------------------------------------------
# Figma property mapping helpers
# ---------------------------------------------------------------------------

# System element name patterns for render_hint
_PLATFORM_PATTERNS = [
    "status bar", "statusbar", "notch", "navigation bar", "navigationbar",
]
_SPACER_PATTERNS = [
    "home indicator", "homeindicator", "safe area", "safearea",
    "tabbar spacer", "tabbarspacer",
]


def detect_render_hint(name: str) -> Optional[str]:
    """Detect system element type from Figma node name."""
    lower = name.lower().replace("-", " ").replace("_", " ")
    for pattern in _PLATFORM_PATTERNS:
        if pattern in lower:
            return "platform"
    for pattern in _SPACER_PATTERNS:
        if pattern in lower:
            return "spacer"
    return None


def _bounds_overlap_ratio(a: Dict, b: Dict) -> float:
    """Calculate overlap ratio between two bounding boxes (relative to smaller)."""
    ax1, ay1 = a.get("x", 0), a.get("y", 0)
    ax2 = ax1 + a.get("width", 0)
    ay2 = ay1 + a.get("height", 0)
    bx1, by1 = b.get("x", 0), b.get("y", 0)
    bx2 = bx1 + b.get("width", 0)
    by2 = by1 + b.get("height", 0)

    ix1 = max(ax1, bx1)
    iy1 = max(ay1, by1)
    ix2 = min(ax2, bx2)
    iy2 = min(ay2, by2)

    if ix1 >= ix2 or iy1 >= iy2:
        return 0.0

    intersection = (ix2 - ix1) * (iy2 - iy1)
    smaller_area = min(
        a.get("width", 0) * a.get("height", 0),
        b.get("width", 0) * b.get("height", 0),
    )
    if smaller_area <= 0:
        return 0.0
    return intersection / smaller_area


def detect_container_layout(node: Dict, children_bounds: List[Dict]) -> Dict:
    """Detect layout type from Figma node properties or children positions.

    Auto-layout → flex. Overlapping children (no layoutMode) → stack. Else → absolute.
    """
    layout_mode = node.get("layoutMode")
    if layout_mode:
        direction = "row" if layout_mode == "HORIZONTAL" else "column"

        justify_map = {
            "MIN": "start", "CENTER": "center", "MAX": "end",
            "SPACE_BETWEEN": "space-between",
        }
        align_map = {
            "MIN": "start", "CENTER": "center", "MAX": "end",
            "STRETCH": "stretch", "BASELINE": "baseline",
        }

        layout: Dict[str, Any] = {
            "type": "flex",
            "direction": direction,
            "justify": justify_map.get(
                node.get("primaryAxisAlignItems", "MIN"), "start"
            ),
            "align": align_map.get(
                node.get("counterAxisAlignItems", "MIN"), "start"
            ),
            "gap": node.get("itemSpacing", 0),
            "padding": [
                node.get("paddingTop", 0),
                node.get("paddingRight", 0),
                node.get("paddingBottom", 0),
                node.get("paddingLeft", 0),
            ],
            "overflow": "hidden" if node.get("clipsContent", False) else "visible",
        }
        if node.get("layoutWrap") == "WRAP":
            layout["wrap"] = True
        return layout

    # No auto-layout: check for stack (overlapping children).
    # Any significant overlap between siblings indicates intentional layering —
    # in normal flex/absolute layouts siblings never overlap.
    if len(children_bounds) >= 2:
        for i in range(len(children_bounds)):
            for j in range(i + 1, len(children_bounds)):
                if _bounds_overlap_ratio(children_bounds[i], children_bounds[j]) > 0.3:
                    return {"type": "stack"}

    return {"type": "absolute"}


def figma_sizing(node: Dict) -> Dict[str, Any]:
    """Extract sizing strategy from Figma node."""
    bbox = node.get("absoluteBoundingBox", {})
    w = bbox.get("width", 0)
    h = bbox.get("height", 0)

    sizing_h = node.get("layoutSizingHorizontal", "FIXED")
    sizing_v = node.get("layoutSizingVertical", "FIXED")

    width_map = {"FIXED": f"{int(w)}px", "FILL": "fill", "HUG": "hug"}
    height_map = {"FIXED": f"{int(h)}px", "FILL": "fill", "HUG": "hug"}

    result: Dict[str, Any] = {
        "width": width_map.get(sizing_h, f"{int(w)}px"),
        "height": height_map.get(sizing_v, f"{int(h)}px"),
    }

    # Min/max constraints
    for figma_key, schema_key in [
        ("minWidth", "min_width"),
        ("maxWidth", "max_width"),
        ("minHeight", "min_height"),
        ("maxHeight", "max_height"),
    ]:
        val = node.get(figma_key)
        if val is not None and val > 0:
            result[schema_key] = val

    # Aspect ratio (if locked)
    if node.get("preserveRatio") and w > 0 and h > 0:
        g = gcd(int(w), int(h))
        result["aspect_ratio"] = f"{int(w) // g}:{int(h) // g}"

    return result


def figma_fills_to_background(fills: List[Dict]) -> Dict[str, Any]:
    """Convert Figma fills[] to style.background."""
    visible_fills = [f for f in fills if f.get("visible", True)]
    if not visible_fills:
        return {"type": "none"}

    # Use last visible fill (Figma renders bottom-up, last = topmost)
    fill = visible_fills[-1]
    fill_type = fill.get("type", "")

    if fill_type == "SOLID":
        color = fill.get("color", {})
        a = color.get("a", 1.0) * fill.get("opacity", 1.0)
        r = round(color.get("r", 0) * 255)
        g = round(color.get("g", 0) * 255)
        b = round(color.get("b", 0) * 255)
        hex_color = f"#{r:02X}{g:02X}{b:02X}"
        if a < 1.0:
            hex_color += f"{round(a * 255):02X}"
        return {"type": "solid", "color": hex_color}

    if fill_type == "GRADIENT_LINEAR":
        gradient_stops = fill.get("gradientStops", [])
        stops = []
        for stop in gradient_stops:
            color = figma_color_to_hex(stop.get("color", {}))
            position = stop.get("position", 0)
            stops.append({"color": color, "position": round(position, 2)})

        # Calculate angle from gradient handle positions
        handle_positions = fill.get("gradientHandlePositions", [])
        angle = 180  # default top-to-bottom
        if len(handle_positions) >= 2:
            p0 = handle_positions[0]
            p1 = handle_positions[1]
            # Handles are in normalized coordinates (0-1)
            dx = (p1.get("x", 0.5) if isinstance(p1, dict) else p1[0]) - \
                 (p0.get("x", 0.5) if isinstance(p0, dict) else p0[0])
            dy = (p1.get("y", 0) if isinstance(p1, dict) else p1[1]) - \
                 (p0.get("y", 0) if isinstance(p0, dict) else p0[1])
            angle = round(math.degrees(math.atan2(dx, -dy)) % 360)

        return {
            "type": "gradient-linear",
            "gradient": {"angle": angle, "stops": stops},
        }

    if fill_type == "GRADIENT_RADIAL":
        gradient_stops = fill.get("gradientStops", [])
        stops = []
        for stop in gradient_stops:
            color = figma_color_to_hex(stop.get("color", {}))
            position = stop.get("position", 0)
            stops.append({"color": color, "position": round(position, 2)})
        return {
            "type": "gradient-radial",
            "gradient": {"stops": stops},
        }

    if fill_type == "IMAGE":
        image_ref = fill.get("imageRef", "")
        scale_mode = fill.get("scaleMode", "FILL")
        fit_map = {"FILL": "cover", "FIT": "contain", "CROP": "cover", "TILE": "none"}
        return {
            "type": "image",
            "image": {
                "url": f"figma://image/{image_ref}" if image_ref else "",
                "fit": fit_map.get(scale_mode, "cover"),
            },
        }

    return {"type": "none"}


def figma_strokes_to_border(node: Dict) -> Optional[Dict[str, Any]]:
    """Convert Figma strokes/strokeWeight to style.border."""
    strokes = node.get("strokes", [])
    visible_strokes = [s for s in strokes if s.get("visible", True)]
    if not visible_strokes:
        return None

    stroke = visible_strokes[0]
    color = figma_color_to_hex(stroke.get("color", {}))
    weight = node.get("strokeWeight", 0)
    if weight <= 0:
        return None

    return {
        "width": weight,
        "color": color,
        "style": "solid",
        "sides": "all",
    }


def figma_effects_to_style(effects: List[Dict]) -> Dict[str, Any]:
    """Extract shadow[], blur from Figma effects[]."""
    result: Dict[str, Any] = {}
    shadows = []

    for effect in effects:
        if not effect.get("visible", True):
            continue
        etype = effect.get("type", "")

        if etype in ("DROP_SHADOW", "INNER_SHADOW"):
            offset = effect.get("offset", {})
            color = figma_color_to_hex(effect.get("color", {}))
            shadows.append({
                "type": "drop" if etype == "DROP_SHADOW" else "inner",
                "x": offset.get("x", 0),
                "y": offset.get("y", 0),
                "blur": effect.get("radius", 0),
                "spread": effect.get("spread", 0),
                "color": color,
            })

        elif etype in ("LAYER_BLUR", "BACKGROUND_BLUR"):
            result["blur"] = {
                "type": "layer" if etype == "LAYER_BLUR" else "background",
                "radius": effect.get("radius", 0),
            }

    if shadows:
        result["shadow"] = shadows

    return result


def figma_corner_radius(node: Dict) -> Any:
    """Extract corner radius from Figma node.

    Returns number (uniform) or [tl, tr, br, bl] (non-uniform) or None.
    """
    radii = node.get("rectangleCornerRadii")
    if radii and isinstance(radii, list) and len(radii) == 4:
        if len(set(radii)) == 1:
            return radii[0] if radii[0] > 0 else None
        return radii

    radius = node.get("cornerRadius", 0)
    return radius if radius > 0 else None


def figma_text_to_typography(node: Dict) -> Optional[Dict[str, Any]]:
    """Extract typography info from a TEXT node."""
    if node.get("type") != "TEXT":
        return None

    style = node.get("style", {})
    characters = node.get("characters", "")

    if not characters and not style:
        return None

    align_map = {
        "LEFT": "left", "CENTER": "center",
        "RIGHT": "right", "JUSTIFIED": "justify",
    }

    result: Dict[str, Any] = {}
    if characters:
        result["content"] = characters
    if style.get("fontFamily"):
        result["font_family"] = style["fontFamily"]
    if style.get("fontSize"):
        result["font_size"] = style["fontSize"]
    if style.get("fontWeight"):
        result["font_weight"] = style["fontWeight"]
    if style.get("lineHeightPx"):
        result["line_height"] = style["lineHeightPx"]
    letter_spacing = style.get("letterSpacing")
    if letter_spacing is not None and letter_spacing != 0:
        result["letter_spacing"] = letter_spacing
    if style.get("textAlignHorizontal"):
        result["align"] = align_map.get(style["textAlignHorizontal"], "left")

    # Text color from fills
    fills = node.get("fills", [])
    visible_fills = [
        f for f in fills
        if f.get("visible", True) and f.get("type") == "SOLID"
    ]
    if visible_fills:
        result["color"] = figma_color_to_hex(visible_fills[0].get("color", {}))

    # Text decoration
    decoration = style.get("textDecoration", "NONE")
    if decoration == "UNDERLINE":
        result["decoration"] = "underline"
    elif decoration == "STRIKETHROUGH":
        result["decoration"] = "strikethrough"

    # Text case
    text_case = style.get("textCase", "ORIGINAL")
    if text_case == "UPPER":
        result["transform"] = "uppercase"
    elif text_case == "LOWER":
        result["transform"] = "lowercase"
    elif text_case == "TITLE":
        result["transform"] = "capitalize"

    return result if result else None


def _to_component_name(figma_name: str) -> str:
    """Convert Figma layer name to PascalCase component name."""
    name = re.sub(r"[^\x00-\x7f]", " ", figma_name)
    parts = re.split(r"[-_\s/]+", name)
    pascal = "".join(p.capitalize() for p in parts if p.strip())
    return pascal or "Component"


# ---------------------------------------------------------------------------
# Core: Figma node → ComponentSpec mapping
# ---------------------------------------------------------------------------


def figma_node_to_component_spec(
    node: Dict,
    z_index: int = 0,
    reverse_map: Optional[Dict[str, str]] = None,
) -> Optional[Dict[str, Any]]:
    """Convert a raw Figma node to a PartialComponentSpec.

    Maps all deterministic fields (70%):
    - id, name, bounds, layout, sizing, style, typography, content
    - render_hint, z_index

    Leaves LLM fields as placeholders:
    - role → "other"
    - description → ""
    - interaction → None
    """
    node_type = node.get("type", "")
    name = node.get("name", "Unknown")
    node_id = node.get("id", "")
    visible = node.get("visible", True)

    if not visible:
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

    # --- Recursively build children ---
    children_specs: List[Dict] = []
    children = node.get("children", [])
    children_bounds: List[Dict] = []
    for i, child in enumerate(children):
        child_spec = figma_node_to_component_spec(
            child, z_index=i, reverse_map=reverse_map,
        )
        if child_spec:
            children_specs.append(child_spec)
            children_bounds.append(child_spec["bounds"])

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

    opacity = node.get("opacity", 1.0)

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

    # Icon detection: small VECTOR or small INSTANCE (≤48px)
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
    component_name = _to_component_name(name)

    spec: Dict[str, Any] = {
        "id": node_id,
        "name": component_name,
        "role": "other",        # Node 2 fills
        "description": "",      # Node 2 fills
        "bounds": bounds,
        "layout": layout,
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


# ---------------------------------------------------------------------------
# Node 1: FrameDecomposerNode
# ---------------------------------------------------------------------------

@register_node_type(
    node_type="frame_decomposer",
    display_name="Frame Decomposer",
    description=(
        "Extracts structural data from Figma node tree into ComponentSpec "
        "format (70% of fields). Applies token reverse mapping and "
        "render_hint detection."
    ),
    category="analysis",
    input_schema={
        "type": "object",
        "properties": {
            "figma_node_tree": {
                "type": "object",
                "description": "Raw Figma node tree from get_file_nodes()",
            },
            "design_tokens": {
                "type": "object",
                "description": "Design tokens (colors, fonts, spacing, radii)",
            },
            "page_name": {"type": "string"},
            "page_node_id": {"type": "string"},
            "file_key": {"type": "string"},
            "file_name": {"type": "string"},
            "device_type": {
                "type": "string",
                "enum": ["mobile", "tablet", "desktop"],
            },
            "screenshot_paths": {
                "type": "object",
                "description": "node_id → screenshot file path mapping",
            },
        },
        "required": ["figma_node_tree"],
    },
    output_schema={
        "type": "object",
        "properties": {
            "components": {
                "type": "array",
                "description": "List of PartialComponentSpec",
            },
            "page": {"type": "object"},
            "design_tokens": {"type": "object"},
            "source": {"type": "object"},
        },
    },
    icon="layers",
    color="#3B82F6",
)
class FrameDecomposerNode(BaseNodeImpl):
    """Node 1: Extracts structural data from Figma node tree.

    Produces PartialComponentSpec for each top-level frame:
    - Fills 70% of fields from Figma API data (layout, sizing, style, typography)
    - Leaves 30% for Node 2 LLM (role, description, interaction)
    - Applies token reverse mapping for ColorValue format
    - Detects render_hint for system elements
    - Computes z_index from children array order
    """

    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        node_tree = inputs.get("figma_node_tree", {})
        design_tokens_raw = inputs.get("design_tokens", {})
        page_name = inputs.get("page_name", "")
        page_node_id = inputs.get("page_node_id", "")
        file_key = inputs.get("file_key", "")
        file_name = inputs.get("file_name", "")
        device_type = inputs.get("device_type")
        screenshot_paths = inputs.get("screenshot_paths", {})

        logger.info(
            "FrameDecomposerNode [%s]: decomposing page '%s' (%s)",
            self.node_id, page_name, page_node_id,
        )

        # Build token reverse map
        reverse_map = build_token_reverse_map(design_tokens_raw)

        # Resolve page document node from various input formats
        page_doc = self._resolve_page_doc(node_tree, page_node_id)

        # Process top-level children
        children = page_doc.get("children", [])
        components: List[Dict] = []
        children_bounds: List[Dict] = []

        for i, child in enumerate(children):
            spec = figma_node_to_component_spec(
                child, z_index=i, reverse_map=reverse_map,
            )
            if spec:
                # Apply token reverse map to all color values
                spec = apply_token_reverse_map(spec, reverse_map)
                # Assign screenshot path if available
                nid = spec["id"]
                if nid in screenshot_paths:
                    spec["screenshot_path"] = screenshot_paths[nid]
                components.append(spec)
                children_bounds.append(spec["bounds"])

        # Detect page-level layout
        if len(components) <= 1:
            page_layout: Dict[str, Any] = {"type": "flex", "direction": "column"}
        else:
            page_layout = detect_container_layout(page_doc, children_bounds)

        # Build page metadata
        page_bbox = page_doc.get("absoluteBoundingBox", {})
        page_width = page_bbox.get("width", 0)
        page_height = page_bbox.get("height", 0)

        page = {
            "name": page_name or page_doc.get("name", ""),
            "node_id": page_node_id or page_doc.get("id", ""),
            "device": {
                "type": device_type or _detect_device_type(page_width),
                "width": page_width,
                "height": page_height,
            },
            "description": "",  # Node 2 fills
            "responsive_strategy": "fixed-width",  # Node 2 may override
            "layout": page_layout,
        }

        # Format design tokens for schema output
        schema_tokens = self._format_design_tokens(design_tokens_raw)

        logger.info(
            "FrameDecomposerNode [%s]: decomposed %d components, "
            "page layout=%s",
            self.node_id, len(components), page_layout.get("type"),
        )

        return {
            "components": components,
            "page": page,
            "design_tokens": schema_tokens,
            "source": {
                "tool": "figma",
                "file_key": file_key,
                "file_name": file_name,
            },
        }

    @staticmethod
    def _resolve_page_doc(node_tree: Dict, page_node_id: str) -> Dict:
        """Resolve the page document node from various input formats.

        Supports:
        1. Raw get_file_nodes() response: {nodes: {node_id: {document: {...}}}}
        2. Direct document node: {type: "FRAME", children: [...]}
        3. Design export format: {components: [...], page_bounds: {...}}
        """
        # Format 1: Raw API response
        if "nodes" in node_tree:
            page_data = node_tree["nodes"].get(page_node_id, {})
            doc = page_data.get("document", {})
            if doc:
                return doc
            # Try first node if specific ID not found
            for nid, ndata in node_tree["nodes"].items():
                return ndata.get("document", {})

        # Format 2: Direct document node (has 'type' and 'children')
        if "type" in node_tree and "children" in node_tree:
            return node_tree

        # Format 3: Design export (has 'components' at top level)
        if "components" in node_tree and "page_bounds" in node_tree:
            logger.warning(
                "FrameDecomposerNode: received design_export format — "
                "layout/sizing/style fields will be incomplete (no raw "
                "Figma properties). Use raw get_file_nodes() response "
                "for full spec extraction."
            )
            return node_tree

        return node_tree

    @staticmethod
    def _format_design_tokens(raw_tokens: Dict) -> Dict[str, Any]:
        """Format design tokens for schema output.

        Converts internal token format to the schema's design_tokens structure:
        {colors: {...}, typography: {font_family, scale}, spacing: {...}, radii: {...}}
        """
        result: Dict[str, Any] = {}

        colors = raw_tokens.get("colors", {})
        if colors:
            result["colors"] = colors

        # Convert fonts structure to schema typography format
        fonts = raw_tokens.get("fonts", {})
        if fonts:
            typography: Dict[str, Any] = {}
            if fonts.get("family"):
                typography["font_family"] = fonts["family"]
            sizes = fonts.get("sizes", {})
            if sizes:
                scale = {}
                for name, size in sizes.items():
                    try:
                        scale[name] = {
                            "size": float(size) if isinstance(size, str) else size
                        }
                    except (ValueError, TypeError):
                        pass
                if scale:
                    typography["scale"] = scale
            if typography:
                result["typography"] = typography

        spacing = raw_tokens.get("spacing", {})
        if spacing:
            spacing_vals: Dict[str, Any] = {}
            radii_vals: Dict[str, Any] = {}
            for name, val in spacing.items():
                try:
                    num_val = float(val) if isinstance(val, str) else val
                except (ValueError, TypeError):
                    continue
                lower_name = name.lower()
                if any(
                    k in lower_name
                    for k in ("radius", "corner", "round")
                ):
                    radii_vals[name] = num_val
                else:
                    spacing_vals[name] = num_val
            if spacing_vals:
                result["spacing"] = spacing_vals
            if radii_vals:
                result["radii"] = radii_vals

        return result


# ---------------------------------------------------------------------------
# Node 2: SpecAnalyzerNode
# ---------------------------------------------------------------------------

# Import prompt templates and merger
from ..spec.spec_analyzer_prompt import (
    SPEC_ANALYZER_OUTPUT_SCHEMA,
    SPEC_ANALYZER_SYSTEM_PROMPT,
    SPEC_ANALYZER_USER_PROMPT,
)
from ..spec.spec_merger import merge_analyzer_output


def _strip_semantic_fields(spec: Dict) -> Dict:
    """Create a copy of ComponentSpec with semantic fields nulled out.

    This is the 'partial spec' sent to the LLM — structural data only.
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


def _parse_analyzer_json(raw: str) -> Optional[Dict]:
    """Extract and parse JSON from LLM response.

    Handles responses that may contain markdown code fences.
    """
    text = raw.strip()
    # Strip markdown code fences
    if text.startswith("```"):
        lines = text.split("\n")
        # Remove first line (```json) and last line (```)
        lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Fallback: extract outermost { ... } (LLM may add preamble/epilogue)
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(text[start:end + 1])
            except json.JSONDecodeError:
                pass
        logger.error("SpecAnalyzerNode: JSON parse error, raw[:500]: %s", text[:500])
        return None


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
    """Node 2: SpecAnalyzer — LLM vision analysis for semantic fields.

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

        model = self.config.get("model", "claude-sonnet-4-20250514")
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

        stats = {"total": len(components), "succeeded": 0, "failed": 0}
        analyzed_components: List[Dict] = []

        for idx, component in enumerate(components):
            comp_name = component.get("name", f"component_{idx}")
            comp_id = component.get("id", "")
            logger.info(
                "SpecAnalyzerNode [%s]: analyzing %s (%d/%d)",
                self.node_id, comp_name, idx + 1, len(components),
            )

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
                )
                analyzed_components.append(result)
                stats["succeeded"] += 1

                # Push SSE event for this component
                if run_id:
                    from ..sse import push_sse_event
                    await push_sse_event(run_id, "spec_analyzed", {
                        "component_id": comp_id,
                        "component_name": comp_name,
                        "role": result.get("role"),
                        "description": result.get("description", "")[:200],
                        "index": idx,
                        "total": len(components),
                    })

            except Exception as e:
                logger.error(
                    "SpecAnalyzerNode [%s]: failed to analyze %s: %s",
                    self.node_id, comp_name, e,
                )
                # Preserve original component, mark as failed
                failed = {**component, "_analysis_failed": True}
                analyzed_components.append(failed)
                stats["failed"] += 1

        logger.info(
            "SpecAnalyzerNode [%s]: done — %d/%d succeeded",
            self.node_id, stats["succeeded"], stats["total"],
        )

        return {
            "components": analyzed_components,
            "analysis_stats": stats,
        }

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
    ) -> Dict:
        """Analyze a single component using Claude CLI subprocess."""
        import asyncio

        # Build partial spec (structural data only)
        partial_spec = _strip_semantic_fields(component)
        partial_spec_json = json.dumps(partial_spec, ensure_ascii=False, indent=2)

        # Build design tokens JSON
        tokens_json = json.dumps(design_tokens, ensure_ascii=False, indent=2)

        # Format user prompt
        user_text = SPEC_ANALYZER_USER_PROMPT.format(
            device_type=device.get("type", "mobile"),
            device_width=device.get("width", 393),
            device_height=device.get("height", 852),
            responsive_strategy=page.get("responsive_strategy", "fixed-width"),
            page_layout_type=page_layout.get("type", "flex"),
            sibling_names=", ".join(sibling_names),
            design_tokens_json=tokens_json,
            partial_spec_json=partial_spec_json,
        )

        # Resolve screenshot absolute path for CLI Read tool
        screenshot_path = component.get("screenshot_path", "")
        screenshot_abs = ""
        if screenshot_path:
            screenshot_abs = (
                screenshot_path
                if os.path.isabs(screenshot_path)
                else os.path.join(cwd, screenshot_path)
            )
            if not os.path.isfile(screenshot_abs):
                logger.warning(
                    "SpecAnalyzerNode: screenshot not found: %s", screenshot_abs
                )
                screenshot_abs = ""

        # Build the full prompt for CLI: system prompt + screenshot ref + user prompt
        cli_prompt_parts = [
            SPEC_ANALYZER_SYSTEM_PROMPT,
            "",
        ]
        if screenshot_abs:
            cli_prompt_parts.append(
                f"First, read the screenshot image at: {screenshot_abs}"
            )
            cli_prompt_parts.append(
                "Use this screenshot as visual context for your analysis."
            )
            cli_prompt_parts.append("")
        cli_prompt_parts.append(user_text)
        cli_prompt = "\n".join(cli_prompt_parts)

        # Build CLI command
        cmd = [
            claude_bin,
            "-p", cli_prompt,
            "--output-format", "json",
            "--model", model,
            "--dangerously-skip-permissions",
            "--no-session-persistence",
        ]
        if screenshot_abs:
            cmd.extend(["--allowedTools", "Read"])
        else:
            cmd.extend(["--tools", ""])

        # Build env: inherit current env but remove CLAUDECODE to avoid
        # nested session detection
        cli_env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}

        logger.info(
            "SpecAnalyzerNode [%s]: calling claude CLI for %s",
            self.node_id, component.get("name", "?"),
        )

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=cli_env,
        )

        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=120.0,
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.communicate()
            raise TimeoutError(
                f"Claude CLI timed out (120s) for {component.get('name')}"
            )

        if proc.returncode != 0:
            err_msg = stderr.decode("utf-8", errors="replace").strip()
            raise RuntimeError(
                f"Claude CLI failed (exit {proc.returncode}) for "
                f"{component.get('name')}: {err_msg[:500]}"
            )

        raw_text = stdout.decode("utf-8", errors="replace").strip()

        # --output-format json wraps the response in a JSON envelope
        # with a "result" field containing the text
        cli_output = None
        try:
            cli_output = json.loads(raw_text)
        except json.JSONDecodeError:
            pass

        # Extract the actual text content from CLI JSON envelope
        if isinstance(cli_output, dict) and "result" in cli_output:
            raw_text = cli_output["result"]
        elif isinstance(cli_output, dict) and "content" in cli_output:
            raw_text = cli_output["content"]

        # Parse JSON output — raise on failure so execute() counts it as failed
        analyzer_output = _parse_analyzer_json(raw_text)
        if not analyzer_output:
            raise ValueError(
                f"JSON parse failed for {component.get('name')}, "
                f"raw[:300]: {raw_text[:300]}"
            )

        # Merge LLM output into component using spec_merger
        return merge_analyzer_output(component, analyzer_output)


# ---------------------------------------------------------------------------
# Node 3: SpecAssemblerNode
# ---------------------------------------------------------------------------

@register_node_type(
    node_type="spec_assembler",
    display_name="Spec Assembler",
    description=(
        "Assembles final design_spec.json from completed ComponentSpecs. "
        "Wraps page metadata, design tokens, source info, and orders "
        "components by z_index."
    ),
    category="output",
    input_schema={
        "type": "object",
        "properties": {
            "components": {
                "type": "array",
                "description": "List of completed ComponentSpec dicts",
            },
            "page": {"type": "object"},
            "design_tokens": {"type": "object"},
            "source": {"type": "object"},
            "output_dir": {"type": "string"},
        },
    },
    output_schema={
        "type": "object",
        "properties": {
            "spec_path": {"type": "string"},
            "spec_document": {"type": "object"},
        },
    },
    icon="file-json",
    color="#10B981",
)
class SpecAssemblerNode(BaseNodeImpl):
    """Node 3: Assembles final design_spec.json.

    1. Wraps page metadata, design_tokens, source info
    2. Orders components by z_index (bottom layer first)
    3. Writes to {output_dir}/design_spec.json
    """

    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        components = inputs.get("components", [])
        page = inputs.get("page", {})
        design_tokens = inputs.get("design_tokens", {})
        source = inputs.get("source", {})
        output_dir = self.config.get("output_dir") or inputs.get("output_dir", "")

        logger.info(
            "SpecAssemblerNode [%s]: assembling %d components",
            self.node_id, len(components),
        )

        # Add exported_at timestamp
        source_with_ts = {
            **source,
            "exported_at": datetime.now(timezone.utc).isoformat(),
        }

        # Sort components by z_index (bottom layer first)
        sorted_components = sorted(
            components,
            key=lambda c: c.get("z_index", 0),
        )

        # Assemble final document
        spec_document = {
            "version": "1.0",
            "source": source_with_ts,
            "page": page,
            "design_tokens": design_tokens,
            "components": sorted_components,
        }

        # Write to disk if output_dir provided
        spec_path = ""
        if output_dir:
            os.makedirs(output_dir, exist_ok=True)
            spec_path = os.path.join(output_dir, "design_spec.json")
            with open(spec_path, "w", encoding="utf-8") as f:
                json.dump(spec_document, f, ensure_ascii=False, indent=2)
            logger.info(
                "SpecAssemblerNode [%s]: wrote %s (%d components)",
                self.node_id, spec_path, len(sorted_components),
            )

        return {
            "spec_path": spec_path,
            "spec_document": spec_document,
        }
