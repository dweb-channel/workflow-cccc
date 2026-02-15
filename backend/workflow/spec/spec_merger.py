"""Merge SpecAnalyzer LLM output into partial ComponentSpec.

Node 2 (SpecAnalyzer) outputs semantic fields (role, description, render_hint,
content_updates, interaction) plus a flattened children_updates array.
This module merges those fields into the partial ComponentSpec tree
produced by Node 1 (FrameDecomposer).
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, List, Optional


def _build_children_map(
    children_updates: List[Dict[str, Any]],
) -> Dict[str, Dict[str, Any]]:
    """Index children_updates by id for O(1) lookup."""
    return {entry["id"]: entry for entry in children_updates if "id" in entry}


def _merge_content_updates(
    component: Dict[str, Any], content_updates: Dict[str, Any]
) -> None:
    """Merge content_updates into component's content field (in-place).

    Only updates fields that the LLM filled (non-null):
    - image_alt -> content.image.alt
    - icon_name -> content.icon.name
    """
    if not content_updates:
        return

    content = component.get("content")
    if not isinstance(content, dict):
        return

    image_alt = content_updates.get("image_alt")
    if image_alt is not None:
        image = content.get("image")
        if isinstance(image, dict):
            image["alt"] = image_alt

    icon_name = content_updates.get("icon_name")
    if icon_name is not None:
        icon = content.get("icon")
        if isinstance(icon, dict):
            icon["name"] = icon_name


def _merge_interaction(
    component: Dict[str, Any], interaction: Dict[str, Any]
) -> None:
    """Merge LLM-generated interaction fields into component (in-place).

    LLM provides: behaviors[], states[] (name+description only).
    Node 1 may have already populated style_overrides and transitions
    from Figma data — those are preserved.
    """
    if not interaction:
        return

    existing = component.get("interaction")
    if not isinstance(existing, dict):
        existing = {}
        component["interaction"] = existing

    # Behaviors: LLM output replaces (Node 1 doesn't generate behaviors)
    behaviors = interaction.get("behaviors")
    if isinstance(behaviors, list):
        existing["behaviors"] = behaviors

    # States: merge LLM descriptions with Node 1 style_overrides
    llm_states = interaction.get("states")
    if isinstance(llm_states, list) and llm_states:
        existing_states = existing.get("states", [])
        existing_by_name = {
            s["name"]: s for s in existing_states if isinstance(s, dict)
        }

        merged_states = []
        for llm_state in llm_states:
            name = llm_state.get("name")
            if not name:
                continue
            if name in existing_by_name:
                # Preserve Node 1's style_overrides, add LLM's description
                merged = existing_by_name[name].copy()
                if "description" in llm_state:
                    merged["description"] = llm_state["description"]
                merged_states.append(merged)
                del existing_by_name[name]
            else:
                merged_states.append(llm_state)

        # Keep any Node 1 states that LLM didn't mention
        for remaining in existing_by_name.values():
            merged_states.append(remaining)

        existing["states"] = merged_states


def _merge_into_component(
    component: Dict[str, Any],
    update: Dict[str, Any],
    children_map: Dict[str, Dict[str, Any]],
) -> None:
    """Merge analyzer output fields into a single component (in-place).

    Then recurse into children, matching by id from children_map.
    """
    # Direct field writes
    if "role" in update:
        component["role"] = update["role"]
    if "description" in update:
        component["description"] = update["description"]
    if "render_hint" in update and update["render_hint"] is not None:
        component["render_hint"] = update["render_hint"]

    # Content updates (image.alt, icon.name)
    content_updates = update.get("content_updates")
    if isinstance(content_updates, dict):
        _merge_content_updates(component, content_updates)

    # Interaction (behaviors, states)
    interaction = update.get("interaction")
    if isinstance(interaction, dict):
        _merge_interaction(component, interaction)

    # Recurse into children
    children = component.get("children")
    if isinstance(children, list):
        for child in children:
            if not isinstance(child, dict):
                continue
            child_id = child.get("id")
            if child_id and child_id in children_map:
                child_update = children_map[child_id]
                _merge_into_component(child, child_update, children_map)


def merge_analyzer_output(
    partial_spec: Dict[str, Any],
    analyzer_output: Dict[str, Any],
) -> Dict[str, Any]:
    """Merge SpecAnalyzer LLM output into a partial ComponentSpec.

    Args:
        partial_spec: A ComponentSpec dict from Node 1 (FrameDecomposer).
                      Has structural fields filled (bounds, layout, sizing,
                      style, typography, content, children) but missing
                      semantic fields (role, description, render_hint,
                      interaction).
        analyzer_output: LLM output from Node 2 (SpecAnalyzer).
                         Contains: role, description, render_hint,
                         content_updates, interaction, children_updates[].

    Returns:
        A new ComponentSpec dict with semantic fields merged in.
        Does not mutate the input.
    """
    result = deepcopy(partial_spec)

    # Build lookup map from flattened children_updates
    children_updates = analyzer_output.get("children_updates", [])
    children_map = _build_children_map(children_updates)

    # Merge top-level component fields
    _merge_into_component(result, analyzer_output, children_map)

    return result
