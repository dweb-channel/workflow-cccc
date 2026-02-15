"""Token reverse mapping for design spec documents.

Converts raw hex color strings and numeric spacing values in ComponentSpec
trees into structured ColorValue/SpacingValue objects with design token
references where available.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, List, Optional


def build_color_token_map(design_tokens: Dict[str, Any]) -> Dict[str, str]:
    """Build hex -> token name reverse lookup from design_tokens.colors.

    Args:
        design_tokens: The design_tokens object from a DesignSpecDocument.

    Returns:
        Dict mapping uppercase hex values to token names.
        e.g. {"#FF6B35": "brand-primary", "#FFFFFF": "text-primary"}
    """
    reverse: Dict[str, str] = {}
    for name, hex_val in design_tokens.get("colors", {}).items():
        if isinstance(hex_val, str):
            reverse[hex_val.upper()] = name
    return reverse


def build_spacing_token_map(design_tokens: Dict[str, Any]) -> Dict[float, str]:
    """Build px_value -> token name reverse lookup from design_tokens.spacing.

    Args:
        design_tokens: The design_tokens object from a DesignSpecDocument.

    Returns:
        Dict mapping numeric px values to token names.
        e.g. {4: "xs", 8: "sm", 16: "md", 24: "lg"}
    """
    reverse: Dict[float, str] = {}
    for name, px_val in design_tokens.get("spacing", {}).items():
        if isinstance(px_val, (int, float)):
            reverse[px_val] = name
    return reverse


def _map_color(value: Any, token_map: Dict[str, str]) -> Any:
    """Convert a single color value to ColorValue object format.

    - string -> {"value": str, "token"?: str}
    - object with "value" -> add "token" if match found
    - None/other -> unchanged
    """
    if value is None:
        return None
    if isinstance(value, str):
        token = token_map.get(value.upper())
        result: Dict[str, Any] = {"value": value}
        if token:
            result["token"] = token
        return result
    if isinstance(value, dict) and "value" in value:
        if "token" not in value:
            token = token_map.get(str(value["value"]).upper())
            if token:
                return {**value, "token": token}
        return value
    return value


def _map_spacing(value: Any, token_map: Dict[float, str]) -> Any:
    """Convert a single spacing value to SpacingValue object format.

    - number -> {"value": num, "token"?: str}
    - object with "value" -> add "token" if match found
    - None/other -> unchanged
    """
    if value is None:
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        token = token_map.get(value)
        result: Dict[str, Any] = {"value": value}
        if token:
            result["token"] = token
        return result
    if isinstance(value, dict) and "value" in value:
        if "token" not in value:
            token = token_map.get(value["value"])
            if token:
                return {**value, "token": token}
        return value
    return value


def _process_style_colors(
    style: Dict[str, Any], color_map: Dict[str, str]
) -> None:
    """Process all color positions within a style object (in-place)."""
    if not style:
        return

    bg = style.get("background")
    if isinstance(bg, dict):
        if "color" in bg:
            bg["color"] = _map_color(bg["color"], color_map)
        gradient = bg.get("gradient")
        if isinstance(gradient, dict):
            stops = gradient.get("stops")
            if isinstance(stops, list):
                for stop in stops:
                    if isinstance(stop, dict) and "color" in stop:
                        stop["color"] = _map_color(stop["color"], color_map)

    border = style.get("border")
    if isinstance(border, dict) and "color" in border:
        border["color"] = _map_color(border["color"], color_map)

    shadows = style.get("shadow")
    if isinstance(shadows, list):
        for shadow in shadows:
            if isinstance(shadow, dict) and "color" in shadow:
                shadow["color"] = _map_color(shadow["color"], color_map)


def _process_component(
    component: Dict[str, Any],
    color_map: Dict[str, str],
    spacing_map: Optional[Dict[float, str]] = None,
) -> None:
    """Process a single ComponentSpec's color and spacing values (in-place)."""
    # Style colors (6 positions)
    style = component.get("style")
    if isinstance(style, dict):
        _process_style_colors(style, color_map)

    # Typography color
    typo = component.get("typography")
    if isinstance(typo, dict) and "color" in typo:
        typo["color"] = _map_color(typo["color"], color_map)

    # Content icon color
    content = component.get("content")
    if isinstance(content, dict):
        icon = content.get("icon")
        if isinstance(icon, dict) and "color" in icon:
            icon["color"] = _map_color(icon["color"], color_map)

    # Interaction states style_overrides (same 6 color positions)
    interaction = component.get("interaction")
    if isinstance(interaction, dict):
        states = interaction.get("states")
        if isinstance(states, list):
            for state in states:
                if isinstance(state, dict):
                    overrides = state.get("style_overrides")
                    if isinstance(overrides, dict):
                        _process_style_colors(overrides, color_map)

    # Spacing values (T3)
    if spacing_map:
        layout = component.get("layout")
        if isinstance(layout, dict):
            if "gap" in layout:
                layout["gap"] = _map_spacing(layout["gap"], spacing_map)
            padding = layout.get("padding")
            if isinstance(padding, list):
                layout["padding"] = [
                    _map_spacing(v, spacing_map) for v in padding
                ]

    # Recurse into children
    children = component.get("children")
    if isinstance(children, list):
        for child in children:
            if isinstance(child, dict):
                _process_component(child, color_map, spacing_map)


def apply_token_reverse_map(
    spec: Dict[str, Any],
    color_map: Dict[str, str],
    spacing_map: Optional[Dict[float, str]] = None,
) -> Dict[str, Any]:
    """Apply token reverse mapping to a ComponentSpec or DesignSpecDocument.

    Recursively converts raw hex color strings to ColorValue objects and
    optionally raw numeric spacing values to SpacingValue objects,
    adding design token references where available.

    Args:
        spec: A ComponentSpec dict or full DesignSpecDocument dict.
              If it has a "components" key, treats it as a document and
              processes all top-level components. Otherwise treats it as
              a single ComponentSpec.
        color_map: Hex -> token name mapping (from build_color_token_map).
        spacing_map: Optional px -> token name mapping (from build_spacing_token_map).

    Returns:
        A new dict with all color/spacing values converted to object format.
    """
    result = deepcopy(spec)

    components = result.get("components")
    if isinstance(components, list):
        for comp in components:
            if isinstance(comp, dict):
                _process_component(comp, color_map, spacing_map)
    else:
        _process_component(result, color_map, spacing_map)

    return result
