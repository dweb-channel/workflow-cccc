"""Figma node classification, component detection, and data parsing helpers.

Pure data-processing functions extracted from FigmaClient. No HTTP calls —
these operate on already-fetched Figma API response dicts.

Used by FigmaClient for:
- Frame classification (rule-based + LLM)
- Component detection from node trees
- Variable/style parsing → design tokens
- Interaction context extraction
- Spatial proximity association
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("workflow.integrations.figma")

# =====================================================================
# Constants
# =====================================================================

# Common mobile screen widths (tolerance ±10px)
MOBILE_WIDTHS = {360, 375, 390, 393, 412, 414, 428, 430}
# Tablet widths
TABLET_WIDTHS = {744, 768, 810, 820, 834}
# Desktop minimum width
DESKTOP_MIN_WIDTH = 1024
# Minimum height for a valid screen frame
SCREEN_MIN_HEIGHT = 500
# Width tolerance for screen matching
WIDTH_TOLERANCE = 10

# Keywords that indicate non-UI content (case-insensitive matching)
EXCLUDE_KEYWORDS = frozenset({
    "参考", "取色", "核查", "备注", "old", "archive", "旧版",
    "废弃", "deprecated", "draft", "temp",
})
# Keywords that indicate interaction specs
INTERACTION_KEYWORDS = frozenset({
    "交互", "说明", "流程", "动画", "效果", "标注", "annotation",
    "interaction", "spec", "flow", "transition",
})
# Keywords that indicate design system content
DESIGN_SYSTEM_KEYWORDS = frozenset({
    "取色", "颜色", "色板", "color", "palette", "token",
    "typography", "字体", "spacing", "间距", "style guide",
})

# Node types that indicate visual annotations (arrows, lines, connectors)
VISUAL_ANNOTATION_TYPES = frozenset({
    "LINE", "ARROW", "VECTOR", "BOOLEAN_OPERATION", "STAR", "POLYGON",
})


# =====================================================================
# Variable / Style Parsing
# =====================================================================


def parse_variables(vars_resp: Dict) -> Dict[str, str]:
    """Parse Figma variables API response into name → value map."""
    result = {}
    meta = vars_resp.get("meta", {})
    variables = meta.get("variables", {})

    for var_id, var_data in variables.items():
        name = var_data.get("name", "")
        resolved = var_data.get("resolvedType", "")
        values_by_mode = var_data.get("valuesByMode", {})

        # Use the first mode's value
        for mode_id, value in values_by_mode.items():
            if resolved == "COLOR" and isinstance(value, dict):
                r = round(value.get("r", 0) * 255)
                g = round(value.get("g", 0) * 255)
                b = round(value.get("b", 0) * 255)
                result[name] = f"#{r:02X}{g:02X}{b:02X}"
            elif isinstance(value, (int, float)):
                result[name] = str(value)
            elif isinstance(value, str):
                result[name] = value
            break  # Only take first mode

    return result


def parse_styles(styles_resp: Dict) -> Dict[str, str]:
    """Parse Figma styles API response into name → value map (limited)."""
    result = {}
    styles = styles_resp.get("meta", {}).get("styles", [])
    for style in styles:
        name = style.get("name", "")
        style_type = style.get("style_type", "")
        if name:
            result[name] = style_type
    return result


def variables_to_design_tokens(
    variables: Dict[str, str],
) -> Dict[str, Any]:
    """Convert raw variable map to structured design_tokens format.

    Classifies variables into colors, fonts, spacing by name patterns.
    """
    tokens: Dict[str, Any] = {
        "colors": {},
        "fonts": {"family": "PingFang SC", "weights": {}, "sizes": {}},
        "spacing": {},
    }

    for name, value in variables.items():
        lower = name.lower()
        css_name = to_css_var_name(name)

        if any(k in lower for k in ["color", "fill", "brand", "text&icon", "bg"]):
            tokens["colors"][css_name] = value
        elif any(k in lower for k in ["font", "text-size", "typography"]):
            tokens["fonts"]["sizes"][css_name] = value
        elif any(k in lower for k in ["spacing", "gap", "padding", "margin"]):
            tokens["spacing"][css_name] = value
        elif any(k in lower for k in ["radius", "corner", "round"]):
            tokens["spacing"][css_name] = value
        elif isinstance(value, str) and value.startswith("#"):
            tokens["colors"][css_name] = value

    return tokens


# =====================================================================
# Text Extraction
# =====================================================================


def extract_text_content(node: Dict) -> List[str]:
    """Recursively extract all text content from a node tree."""
    texts = []
    if node.get("type") == "TEXT":
        chars = node.get("characters", "")
        if chars and chars.strip():
            texts.append(chars.strip())

    for child in node.get("children", []):
        texts.extend(extract_text_content(child))

    return texts


# =====================================================================
# Name Conversion
# =====================================================================


def to_component_name(figma_name: str) -> str:
    """Convert Figma layer name to PascalCase component name.

    'photo-grid' → 'PhotoGrid'
    'Header 区域' → 'Header'
    'bottom_nav' → 'BottomNav'
    """
    name = re.sub(r"[^\x00-\x7f]", " ", figma_name)
    parts = re.split(r"[-_\s/]+", name)
    pascal = "".join(p.capitalize() for p in parts if p.strip())
    return pascal or "Component"


def to_css_var_name(figma_name: str) -> str:
    """Convert Figma variable name to CSS-friendly name.

    'Text Color/字体_黑60%' → 'text-color-60'
    'Brand-主题色/品牌色 (100%)' → 'brand-100'
    """
    name = figma_name.lower()
    name = re.sub(r"[/\\]", "-", name)
    name = re.sub(r"[_\s]+", "-", name)
    name = re.sub(r"[()%]+", "", name)
    name = re.sub(r"[^\x00-\x7f]", "", name)
    name = re.sub(r"-+", "-", name)
    name = name.strip("-")
    return name or "unknown"


# =====================================================================
# Component Detection
# =====================================================================


def detect_components_from_tree(
    children: List[Dict],
    page_bounds: Dict,
) -> Tuple[List[Dict[str, Any]], List[str]]:
    """Detect components from Figma node tree children.

    Uses heuristics based on node type, size, and structure.

    Returns:
        Tuple of (components list, all node IDs for screenshot download).
    """
    components = []
    all_node_ids = []
    page_area = page_bounds.get("width", 1) * page_bounds.get("height", 1)

    for child in children:
        comp = node_to_component(child, page_area)
        if comp:
            components.append(comp)
            all_node_ids.append(comp["node_id"])

    # Compute neighbors (adjacent components by vertical position)
    components.sort(key=lambda c: c.get("bounds", {}).get("y", 0))
    for i, comp in enumerate(components):
        neighbors = []
        if i > 0:
            neighbors.append(components[i - 1]["name"])
        if i < len(components) - 1:
            neighbors.append(components[i + 1]["name"])
        comp["neighbors"] = neighbors

    return components, all_node_ids


def node_to_component(
    node: Dict, page_area: float,
) -> Optional[Dict[str, Any]]:
    """Convert a Figma node to a component descriptor.

    Returns None for nodes that shouldn't be treated as components
    (e.g. invisible, zero-size, pure groups).
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

    children = node.get("children", [])
    children_count = len(children)
    area = width * height
    area_ratio = area / page_area if page_area > 0 else 0

    if area_ratio > 0.25:
        comp_type = "section"
    elif children_count > 8:
        comp_type = "organism"
    elif children_count >= 3:
        comp_type = "molecule"
    else:
        comp_type = "atom"

    # Build children summary (first level only, max 10)
    children_summary = []
    for child in children[:10]:
        child_bbox = child.get("absoluteBoundingBox", {})
        child_children = child.get("children", [])
        child_count = len(child_children)

        if child_count > 8:
            child_type = "organism"
        elif child_count >= 3:
            child_type = "molecule"
        else:
            child_type = "atom"

        children_summary.append({
            "name": child.get("name", ""),
            "node_id": child.get("id", ""),
            "type": child_type,
            "bounds": {
                "x": child_bbox.get("x", 0),
                "y": child_bbox.get("y", 0),
                "width": child_bbox.get("width", 0),
                "height": child_bbox.get("height", 0),
            },
        })

    text_content = extract_text_content(node)
    component_name = to_component_name(name)

    return {
        "node_id": node_id,
        "name": component_name,
        "type": comp_type,
        "bounds": bounds,
        "children_summary": children_summary,
        "text_content": text_content,
        "neighbors": [],  # Filled in by caller
        "screenshot_path": None,
        "notes": f"Figma node '{name}' ({node_type}), {children_count} children",
    }


# =====================================================================
# Interaction Context Extraction (D5)
# =====================================================================


def detect_visual_annotations(node: Dict) -> set:
    """Recursively detect visual annotation node types in a subtree.

    Looks for LINE, ARROW, VECTOR, BOOLEAN_OPERATION, STAR, POLYGON
    nodes that typically indicate design annotations.

    Returns:
        Set of detected annotation type strings.
    """
    found: set = set()
    node_type = node.get("type", "")
    if node_type in VISUAL_ANNOTATION_TYPES:
        found.add(node_type)

    for child in node.get("children", []):
        found.update(detect_visual_annotations(child))

    return found


def extract_interaction_context(node: Dict) -> Dict[str, Any]:
    """Extract interaction context from an annotation/spec frame.

    Returns:
        Dict with text_content, has_visual_annotations,
        visual_annotation_types, node_id, name.
    """
    text_content = extract_text_content(node)
    visual_types = detect_visual_annotations(node)

    return {
        "text_content": text_content,
        "has_visual_annotations": len(visual_types) > 0,
        "visual_annotation_types": sorted(visual_types),
        "node_id": node.get("id", ""),
        "name": node.get("name", ""),
    }


# =====================================================================
# Frame Classification (D1)
# =====================================================================


def classify_frame_by_rules(node: Dict) -> Dict[str, Any]:
    """Classify a single top-level frame using rule-based heuristics.

    Returns a classification dict with:
        - node_id, name, size, bounds
        - classification: 'ui_screen' | 'interaction_spec' | 'design_system' | 'excluded' | 'unknown'
        - confidence: 0.0-1.0
        - device_type: 'mobile' | 'tablet' | 'desktop' | None
        - reason: explanation of classification decision
    """
    name = node.get("name", "")
    node_id = node.get("id", "")
    visible = node.get("visible", True)
    bbox = node.get("absoluteBoundingBox", {})
    w = bbox.get("width", 0)
    h = bbox.get("height", 0)
    lower_name = name.lower()

    base = {
        "node_id": node_id,
        "name": name,
        "size": f"{int(w)}×{int(h)}",
        "bounds": {
            "x": bbox.get("x", 0),
            "y": bbox.get("y", 0),
            "width": w,
            "height": h,
        },
    }

    # Invisible → excluded
    if not visible:
        return {
            **base,
            "classification": "excluded",
            "confidence": 0.99,
            "device_type": None,
            "reason": "invisible",
        }

    # Zero-size → excluded
    if w <= 0 or h <= 0:
        return {
            **base,
            "classification": "excluded",
            "confidence": 0.99,
            "device_type": None,
            "reason": "zero_size",
        }

    # --- Keyword-based exclusion (highest priority) ---
    for kw in EXCLUDE_KEYWORDS:
        if kw in lower_name:
            return {
                **base,
                "classification": "excluded",
                "confidence": 0.9,
                "device_type": None,
                "reason": f"keyword_match:{kw}",
            }

    # --- Size-based classification (before soft keywords) ---

    # Check mobile screen sizes
    is_mobile = (
        any(abs(w - mw) <= WIDTH_TOLERANCE for mw in MOBILE_WIDTHS)
        and h >= SCREEN_MIN_HEIGHT
    )
    if is_mobile:
        return {
            **base,
            "classification": "ui_screen",
            "confidence": 0.95,
            "device_type": "mobile",
            "reason": f"mobile_size:{int(w)}×{int(h)}",
        }

    # Check tablet sizes
    is_tablet = (
        any(abs(w - tw) <= WIDTH_TOLERANCE for tw in TABLET_WIDTHS)
        and h >= SCREEN_MIN_HEIGHT
    )
    if is_tablet:
        return {
            **base,
            "classification": "ui_screen",
            "confidence": 0.9,
            "device_type": "tablet",
            "reason": f"tablet_size:{int(w)}×{int(h)}",
        }

    # Check desktop sizes
    if w >= DESKTOP_MIN_WIDTH and h >= SCREEN_MIN_HEIGHT:
        return {
            **base,
            "classification": "ui_screen",
            "confidence": 0.8,
            "device_type": "desktop",
            "reason": f"desktop_size:{int(w)}×{int(h)}",
        }

    # --- Extreme aspect ratio → excluded (banners, strips) ---
    if w > 0 and h > 0:
        aspect = h / w
        if aspect < 0.2 and w >= 800:
            return {
                **base,
                "classification": "excluded",
                "confidence": 0.7,
                "device_type": None,
                "reason": f"wide_banner:{int(w)}×{int(h)}",
            }

    # --- Soft keyword classification (after size check) ---

    # Design system keywords
    for kw in DESIGN_SYSTEM_KEYWORDS:
        if kw in lower_name:
            return {
                **base,
                "classification": "design_system",
                "confidence": 0.85,
                "device_type": None,
                "reason": f"keyword_match:{kw}",
            }

    # Interaction spec keywords
    for kw in INTERACTION_KEYWORDS:
        if kw in lower_name:
            return {
                **base,
                "classification": "interaction_spec",
                "confidence": 0.85,
                "device_type": None,
                "reason": f"keyword_match:{kw}",
            }

    # --- Fallback: unknown (needs LLM classification) ---
    return {
        **base,
        "classification": "unknown",
        "confidence": 0.0,
        "device_type": None,
        "reason": "no_rule_match",
    }


def associate_specs_to_screens(
    screens: List[Dict],
    specs: List[Dict],
) -> None:
    """Associate interaction specs to their nearest UI screen by spatial proximity.

    Uses center-to-center distance between bounding boxes.
    Also tries name prefix matching as a secondary signal.

    Mutates specs in-place: adds 'related_to' field.
    """
    if not screens or not specs:
        return

    for spec in specs:
        spec_bounds = spec.get("bounds", {})
        spec_cx = spec_bounds.get("x", 0) + spec_bounds.get("width", 0) / 2
        spec_cy = spec_bounds.get("y", 0) + spec_bounds.get("height", 0) / 2
        spec_name = spec.get("name", "").lower()

        best_screen = None
        best_distance = float("inf")

        for screen in screens:
            scr_bounds = screen.get("bounds", {})
            scr_cx = scr_bounds.get("x", 0) + scr_bounds.get("width", 0) / 2
            scr_cy = scr_bounds.get("y", 0) + scr_bounds.get("height", 0) / 2
            scr_name = screen.get("name", "").lower()

            dist = ((spec_cx - scr_cx) ** 2 + (spec_cy - scr_cy) ** 2) ** 0.5

            name_bonus = 0
            if scr_name and spec_name:
                shorter = min(scr_name, spec_name, key=len)
                longer = max(scr_name, spec_name, key=len)
                if longer.startswith(shorter) and len(shorter) >= 2:
                    name_bonus = 5000

            effective_dist = dist - name_bonus

            if effective_dist < best_distance:
                best_distance = effective_dist
                best_screen = screen

        if best_screen:
            spec["related_to"] = {
                "node_id": best_screen["node_id"],
                "name": best_screen["name"],
            }
