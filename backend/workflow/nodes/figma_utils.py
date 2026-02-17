"""Figma utility functions — color/token mapping + property extraction.

Provides deterministic conversion from Figma API data structures to
the ComponentSpec schema fields: colors, layout, sizing, typography,
backgrounds, borders, effects, and component naming.
"""

import math
import re
from math import gcd
from typing import Any, Dict, List, Optional

import logging

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
    """Build value -> token_name reverse lookup dictionary.

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

    Auto-layout -> flex. Overlapping children (no layoutMode) -> stack. Else -> absolute.
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
    # Any significant overlap between siblings indicates intentional layering --
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
    # Fallback: some Figma exports use "typeStyle" instead of "style"
    if not style.get("fontFamily"):
        style = node.get("typeStyle", style)
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


_FIGMA_AUTO_NAME_RE = re.compile(
    r"^(Frame|Group|Rectangle|Ellipse|Line|Vector|Component|Instance|Image|"
    r"Union|Subtract|Intersect|Exclude|Mask\s*Group)"
    r"\s*\d{2,}$",
    re.IGNORECASE,
)


def _to_component_name(figma_name: str) -> str:
    """Convert Figma layer name to PascalCase component name.

    Detects Figma auto-generated names (e.g. "Frame 1321317615",
    "Rectangle 240648907") and strips the numeric ID, leaving just
    the type name (e.g. "Frame", "Rectangle"). The dedup logic in
    _rebuild_paths() will add _1, _2 suffixes for same-name siblings.
    """
    # Strip Figma auto-generated numeric IDs
    m = _FIGMA_AUTO_NAME_RE.match(figma_name.strip())
    if m:
        figma_name = m.group(1).strip()

    name = re.sub(r"[^\x00-\x7f]", " ", figma_name)
    parts = re.split(r"[-_\s/]+", name)
    pascal = "".join(p.capitalize() for p in parts if p.strip())
    return pascal or "Component"
