"""Figma API response → design_export.json converter.

Transforms raw Figma REST API responses (node tree, styles, images)
into the design_export.json format consumed by the design-to-code pipeline.

Expected inputs (from figma_client.py):
- file_nodes: Response from GET /v1/files/:key/nodes?ids=<page_node_id>
- file_styles: Response from GET /v1/files/:key/styles (optional)
- image_urls: Response from GET /v1/images/:key (node_id → screenshot URL mapping)
- screenshots_dir: Local directory where pre-fetched screenshots are saved

Output:
- design_export dict matching the schema in data/design_export/design_export.json
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


def convert_figma_to_design_export(
    file_key: str,
    page_node_id: str,
    file_nodes_response: Dict[str, Any],
    screenshots_dir: str,
    file_styles_response: Optional[Dict[str, Any]] = None,
    image_urls: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Convert Figma API responses into design_export.json format.

    Args:
        file_key: Figma file key
        page_node_id: Node ID of the target page/frame
        file_nodes_response: Response from GET /v1/files/:key/nodes
        screenshots_dir: Directory containing pre-fetched component screenshots
        file_styles_response: Optional response from GET /v1/files/:key/styles
        image_urls: Optional mapping of node_id → screenshot URL from /v1/images

    Returns:
        Dict matching design_export.json schema
    """
    file_name = file_nodes_response.get("name", "Untitled")

    # Extract the target node's document tree
    nodes_map = file_nodes_response.get("nodes", {})
    page_entry = nodes_map.get(page_node_id)
    if page_entry is None:
        # Try URL-encoded format (Figma sometimes uses "1:10" or "1-10")
        for key, val in nodes_map.items():
            if val is not None:
                page_entry = val
                break

    if page_entry is None:
        raise ValueError(
            f"Node '{page_node_id}' not found in Figma response. "
            f"Available nodes: {list(nodes_map.keys())}"
        )

    document = page_entry.get("document", {})
    styles_meta = page_entry.get("styles", {})
    components_meta = page_entry.get("components", {})

    # Extract page-level info
    page_bounds = _extract_bounds(document)
    page_name = document.get("name", file_name)

    # Collect raw Figma variables from styles metadata
    variables = _extract_variables(styles_meta, file_styles_response)

    # Identify top-level component frames (direct children of the page)
    children = document.get("children", [])
    if not children:
        # If the requested node IS the component (not a page), treat it as single
        children = [document]

    # Build component list from top-level frames
    components = []
    for i, child in enumerate(children):
        node_type = child.get("type", "")
        # Skip non-visual nodes
        if node_type in ("BOOLEAN_OPERATION", "SLICE"):
            continue

        comp = _build_component(
            node=child,
            screenshots_dir=screenshots_dir,
            image_urls=image_urls,
        )
        components.append(comp)

    # Assign neighbors based on vertical order
    for i, comp in enumerate(components):
        neighbors = []
        if i > 0:
            neighbors.append(components[i - 1]["name"])
        if i < len(components) - 1:
            neighbors.append(components[i + 1]["name"])
        comp["neighbors"] = neighbors

    # Extract design tokens from the node tree + styles
    design_tokens = _extract_design_tokens(document, styles_meta, variables)

    return {
        "version": "1.0",
        "source": "figma",
        "file_key": file_key,
        "page_name": page_name,
        "page_node_id": page_node_id,
        "page_bounds": page_bounds,
        "variables": variables,
        "design_tokens": design_tokens,
        "components": components,
    }


# --- Component extraction ---


def _build_component(
    node: Dict[str, Any],
    screenshots_dir: str,
    image_urls: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Build a component entry from a Figma node."""
    node_id = node.get("id", "")
    name = _sanitize_name(node.get("name", "Unknown"))
    bounds = _extract_bounds(node)

    # Build children summary from direct children
    children_summary = []
    for child in node.get("children", []):
        child_name = _sanitize_name(child.get("name", "?"))
        child_bounds = _extract_bounds(child)
        child_type = _classify_component_type(child)
        children_summary.append({
            "name": child_name,
            "node_id": child.get("id", ""),
            "type": child_type,
            "bounds": child_bounds,
        })

    # Extract all text content by walking the tree
    text_content = _extract_text_content(node)

    # Determine component type based on structure
    comp_type = _classify_component_type(node)

    # Screenshot path — check for pre-fetched file
    screenshot_filename = f"{_safe_filename(node_id)}.png"
    screenshot_path = f"screenshots/{screenshot_filename}"
    abs_screenshot = os.path.join(screenshots_dir, screenshot_filename)
    if not os.path.exists(abs_screenshot):
        screenshot_path = None

    # Generate notes from structure
    notes = _generate_notes(node, text_content, children_summary)

    comp = {
        "node_id": node_id,
        "name": name,
        "type": comp_type,
        "bounds": bounds,
        "children_summary": children_summary,
        "text_content": text_content,
        "neighbors": [],  # Filled in by caller
        "notes": notes,
    }
    if screenshot_path:
        comp["screenshot_path"] = screenshot_path

    return comp


def _extract_bounds(node: Dict[str, Any]) -> Dict[str, Any]:
    """Extract bounding box from a Figma node."""
    bbox = node.get("absoluteBoundingBox") or node.get("bounds", {})
    return {
        "x": bbox.get("x", 0),
        "y": bbox.get("y", 0),
        "width": bbox.get("width", 0),
        "height": bbox.get("height", 0),
    }


def _extract_text_content(node: Dict[str, Any]) -> List[str]:
    """Recursively extract text content from a node tree."""
    texts = []
    if node.get("type") == "TEXT":
        chars = node.get("characters", "")
        if chars and chars.strip():
            texts.append(chars.strip())
    for child in node.get("children", []):
        texts.extend(_extract_text_content(child))
    return texts


def _classify_component_type(node: Dict[str, Any]) -> str:
    """Classify a Figma node into atomic design type.

    Categories:
    - atom: Leaf elements (text, icon, image, button)
    - molecule: Small groups of atoms (tab item, card header)
    - organism: Complex components (header, navigation bar)
    - section: Large page sections (content area, grid)
    """
    children = node.get("children", [])
    node_type = node.get("type", "")

    # Leaf nodes
    if node_type in ("TEXT", "VECTOR", "BOOLEAN_OPERATION", "LINE", "STAR",
                      "ELLIPSE", "REGULAR_POLYGON"):
        return "atom"

    # No children = atom
    if not children:
        return "atom"

    # Count depth and grandchildren
    grandchild_count = sum(len(c.get("children", [])) for c in children)
    bounds = _extract_bounds(node)
    area = bounds.get("width", 0) * bounds.get("height", 0)

    # Large area + deep nesting = section
    if area > 100000 and grandchild_count > 5:
        return "section"

    # Medium complexity = organism
    if len(children) > 3 or grandchild_count > 3:
        return "organism"

    # Small groups = molecule
    if len(children) > 1:
        return "molecule"

    return "atom"


def _generate_notes(
    node: Dict[str, Any],
    text_content: List[str],
    children_summary: List[Dict],
) -> str:
    """Generate a descriptive note for a component."""
    parts = []
    node_type = node.get("type", "FRAME")
    name = node.get("name", "")

    # Describe structure
    child_count = len(children_summary)
    if child_count > 0:
        child_names = ", ".join(c["name"] for c in children_summary[:5])
        if child_count > 5:
            child_names += f" (+{child_count - 5} more)"
        parts.append(f"{name} with {child_count} children: {child_names}")
    else:
        parts.append(name)

    # Describe visible text
    if text_content:
        visible_text = ", ".join(f"'{t}'" for t in text_content[:5])
        if len(text_content) > 5:
            visible_text += f" (+{len(text_content) - 5} more)"
        parts.append(f"Text: {visible_text}")

    # Describe fills (colors)
    fills = node.get("fills", [])
    for fill in fills[:2]:
        if fill.get("type") == "SOLID" and fill.get("visible", True):
            color = fill.get("color", {})
            hex_color = _rgba_to_hex(color)
            parts.append(f"Background: {hex_color}")

    # Describe corner radius
    radius = node.get("cornerRadius")
    if radius and radius > 0:
        parts.append(f"Radius: {radius}px")

    return ". ".join(parts)


# --- Design tokens extraction ---


def _extract_design_tokens(
    document: Dict[str, Any],
    styles_meta: Dict[str, Any],
    variables: Dict[str, str],
) -> Dict[str, Any]:
    """Extract design tokens from the Figma node tree and styles.

    Walks the tree to collect:
    - Colors from fills and styles
    - Fonts from text nodes
    - Spacing from padding/itemSpacing
    - Border radius from cornerRadius
    """
    colors: Dict[str, str] = {}
    fonts: Dict[str, Any] = {"family": "", "weights": {}}
    spacing: Dict[str, str] = {}
    radius: Dict[str, str] = {}

    # Extract from Figma variables (style names → colors)
    for var_name, var_value in variables.items():
        normalized = _normalize_token_name(var_name)
        if var_value.startswith("#"):
            colors[normalized] = var_value

    # Walk tree to collect tokens
    _collect_tokens_from_tree(document, colors, fonts, spacing, radius)

    # Ensure we have at least brand-primary if variables had it
    for var_name, var_value in variables.items():
        lower = var_name.lower()
        if "品牌" in lower or "brand" in lower or "主题" in lower:
            if "brand-primary" not in colors:
                colors["brand-primary"] = var_value
        if "背景" in lower or "background" in lower:
            if "bg-white" not in colors and var_value.upper() in ("#FFFFFF", "#FFF"):
                colors["bg-white"] = var_value
            elif "bg-light" not in colors:
                colors["bg-light"] = var_value

    return {
        "colors": colors,
        "fonts": fonts,
        "spacing": spacing,
        "radius": radius,
    }


def _collect_tokens_from_tree(
    node: Dict[str, Any],
    colors: Dict[str, str],
    fonts: Dict[str, Any],
    spacing: Dict[str, str],
    radius: Dict[str, str],
) -> None:
    """Recursively collect design tokens from a Figma node tree."""
    # Colors from fills
    for fill in node.get("fills", []):
        if fill.get("type") == "SOLID" and fill.get("visible", True):
            color = fill.get("color", {})
            hex_val = _rgba_to_hex(color)
            # Only collect named/meaningful colors, skip if already have enough
            if len(colors) < 20:
                _add_color_if_meaningful(colors, hex_val)

    # Fonts from text nodes
    if node.get("type") == "TEXT":
        style = node.get("style", {})
        family = style.get("fontFamily", "")
        weight = style.get("fontWeight")
        if family and not fonts["family"]:
            fonts["family"] = family
        if weight:
            weight_name = _weight_to_name(weight)
            if weight_name and weight_name not in fonts["weights"]:
                fonts["weights"][weight_name] = weight

    # Spacing from layout properties
    padding_left = node.get("paddingLeft")
    padding_top = node.get("paddingTop")
    item_spacing = node.get("itemSpacing")

    if padding_left and padding_left > 0:
        _add_spacing(spacing, "page-padding", padding_left)
    if padding_top and padding_top > 0:
        _add_spacing(spacing, "card-padding", padding_top)
    if item_spacing and item_spacing > 0:
        _add_spacing(spacing, "section-gap", item_spacing)

    # Border radius
    corner_radius = node.get("cornerRadius")
    if corner_radius and corner_radius > 0:
        _add_radius(radius, corner_radius)

    # Recurse into children
    for child in node.get("children", []):
        _collect_tokens_from_tree(child, colors, fonts, spacing, radius)


def _extract_variables(
    styles_meta: Dict[str, Any],
    file_styles_response: Optional[Dict[str, Any]] = None,
) -> Dict[str, str]:
    """Extract raw Figma variables/styles as name → value mapping.

    Combines styles from the node response and the file-level styles endpoint.
    """
    variables: Dict[str, str] = {}

    # From node-level styles metadata
    for style_id, style_info in styles_meta.items():
        if isinstance(style_info, dict):
            name = style_info.get("name", "")
            # Style metadata from nodes doesn't include the value directly,
            # but we capture the names for cross-referencing
            if name:
                variables[name] = ""

    # From file-level styles response
    if file_styles_response:
        meta = file_styles_response.get("meta", {})
        for style in meta.get("styles", []):
            name = style.get("name", "")
            style_type = style.get("style_type", "")
            if name:
                variables[name] = f"({style_type})"

    return variables


# --- Helper functions ---


def _sanitize_name(name: str) -> str:
    """Convert a Figma layer name to a valid component name.

    Examples:
        "Header Bar / Main" → "HeaderBarMain"
        "status-bar" → "StatusBar"
        "photo_grid_v2" → "PhotoGridV2"
    """
    # Remove special chars except alphanumeric and spaces/separators
    cleaned = re.sub(r"[^\w\s\-/]", "", name)
    # Split on separators
    parts = re.split(r"[\s\-_/]+", cleaned)
    # PascalCase
    return "".join(p.capitalize() for p in parts if p)


def _safe_filename(node_id: str) -> str:
    """Convert a node ID to a safe filename.

    "16650:539" → "16650_539"
    """
    return node_id.replace(":", "_").replace("/", "_")


def _rgba_to_hex(color: Dict[str, float]) -> str:
    """Convert Figma RGBA (0-1 range) to hex color string."""
    r = int(color.get("r", 0) * 255)
    g = int(color.get("g", 0) * 255)
    b = int(color.get("b", 0) * 255)
    return f"#{r:02X}{g:02X}{b:02X}"


def _normalize_token_name(figma_name: str) -> str:
    """Normalize a Figma style/variable name to a CSS token name.

    Examples:
        "Text Color/字体_黑60%" → "text-secondary"
        "Brand-主题色/品牌色 (100%)" → "brand-primary"
        "Background/背景_白" → "bg-white"
    """
    lower = figma_name.lower()

    # Brand colors
    if "品牌" in lower or "brand" in lower or "主题" in lower:
        if "100%" in lower or "primary" in lower or "品牌色" in lower:
            return "brand-primary"
        return "brand-secondary"

    # Text colors
    if "字体" in lower or "text" in lower or "font" in lower:
        if "黑60" in lower or "secondary" in lower:
            return "text-secondary"
        if "黑30" in lower or "tertiary" in lower or "hint" in lower:
            return "text-tertiary"
        return "text-primary"

    # Background
    if "背景" in lower or "background" in lower or "bg" in lower:
        if "白" in lower or "white" in lower:
            return "bg-white"
        if "页面" in lower or "page" in lower or "light" in lower:
            return "bg-light"
        return "bg-white"

    # Border
    if "边框" in lower or "border" in lower or "stroke" in lower:
        return "border"

    # Fallback: slugify
    slug = re.sub(r"[^a-z0-9]+", "-", lower).strip("-")
    return slug or "unknown"


def _weight_to_name(weight: int) -> str:
    """Map font weight number to name."""
    weight_map = {
        100: "thin",
        200: "extralight",
        300: "light",
        400: "regular",
        500: "medium",
        600: "semibold",
        700: "bold",
        800: "extrabold",
        900: "black",
    }
    return weight_map.get(weight, "")


def _add_color_if_meaningful(colors: Dict[str, str], hex_val: str) -> None:
    """Add a color to the tokens dict if it's not pure black/white/transparent."""
    # Skip very common/meaningless colors
    if hex_val.upper() in ("#000000", "#FFFFFF", "#000", "#FFF"):
        return
    # Skip if already collected
    if hex_val in colors.values():
        return
    # Auto-name based on count
    idx = len(colors)
    colors[f"accent-{idx}"] = hex_val


def _add_spacing(spacing: Dict[str, str], hint: str, value: float) -> None:
    """Add a spacing token, avoiding duplicates."""
    px_val = f"{int(value)}px"
    if px_val not in spacing.values():
        if hint not in spacing:
            spacing[hint] = px_val


def _add_radius(radius: Dict[str, str], value: float) -> None:
    """Add a border-radius token."""
    px_val = f"{int(value)}px"
    if px_val not in radius.values():
        # Classify radius
        if value >= 50:
            name = "avatar"
            px_val = "50%"
        elif value >= 16:
            name = "button"
        elif value >= 10:
            name = "card"
        else:
            name = f"sm-{int(value)}"
        if name not in radius:
            radius[name] = px_val
