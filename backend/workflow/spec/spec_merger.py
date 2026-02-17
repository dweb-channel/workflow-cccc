"""Merge SpecAnalyzer LLM output into partial ComponentSpec.

Node 2 (SpecAnalyzer) outputs semantic fields (role, description, render_hint,
content_updates, interaction) plus a flattened children_updates array.
This module merges those fields into the partial ComponentSpec tree
produced by Node 1 (FrameDecomposer).
"""

from __future__ import annotations

import logging
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class MergeReport:
    """Tracks merge statistics and warnings for downstream validation."""

    children_updates_total: int = 0
    children_updates_matched: int = 0
    children_updates_unmatched: List[str] = field(default_factory=list)
    empty_descriptions: List[str] = field(default_factory=list)

    @property
    def children_updates_loss_rate(self) -> float:
        if self.children_updates_total == 0:
            return 0.0
        return len(self.children_updates_unmatched) / self.children_updates_total

    def to_dict(self) -> Dict[str, Any]:
        return {
            "children_updates_total": self.children_updates_total,
            "children_updates_matched": self.children_updates_matched,
            "children_updates_unmatched": self.children_updates_unmatched,
            "children_updates_loss_rate": round(self.children_updates_loss_rate, 2),
            "empty_descriptions": self.empty_descriptions,
        }


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


def _apply_update_fields(
    component: Dict[str, Any],
    update: Dict[str, Any],
    report: Optional[MergeReport] = None,
) -> None:
    """Apply semantic fields from an update dict into a component (in-place)."""
    if "role" in update:
        component["role"] = update["role"]
    if "description" in update:
        component["description"] = update["description"]
    if "render_hint" in update and update["render_hint"] is not None:
        component["render_hint"] = update["render_hint"]
    # LLM-suggested semantic name replaces Figma layer name
    suggested = update.get("suggested_name")
    if suggested and isinstance(suggested, str) and suggested.strip():
        component["name"] = suggested.strip()
    # Free-form design analysis from LLM (always write, even empty, for traceability)
    if "design_analysis" in update:
        component["design_analysis"] = update["design_analysis"]

    # Track empty descriptions
    if report is not None:
        desc = component.get("description", "")
        if not desc or (isinstance(desc, str) and not desc.strip()):
            comp_id = component.get("id", "unknown")
            comp_name = component.get("name", "unknown")
            report.empty_descriptions.append(f"{comp_name}({comp_id})")

    # Content updates (image.alt, icon.name)
    content_updates = update.get("content_updates")
    if isinstance(content_updates, dict):
        _merge_content_updates(component, content_updates)

    # Interaction (behaviors, states)
    interaction = update.get("interaction")
    if isinstance(interaction, dict):
        _merge_interaction(component, interaction)


def _merge_into_component(
    component: Dict[str, Any],
    update: Dict[str, Any],
    children_map: Dict[str, Dict[str, Any]],
    report: Optional[MergeReport] = None,
) -> None:
    """Merge analyzer output fields into a single component (in-place).

    Then recurse into ALL children unconditionally, so deep descendants
    can be matched even when their parent has no update in children_map.
    """
    # Apply semantic fields from the update
    _apply_update_fields(component, update, report)

    # Recurse into ALL children (full-tree walk for deep matching)
    _walk_children_for_updates(component, children_map, report)


def _walk_children_for_updates(
    node: Dict[str, Any],
    children_map: Dict[str, Dict[str, Any]],
    report: Optional[MergeReport] = None,
) -> None:
    """Walk ALL children recursively, applying updates where IDs match.

    This ensures deep descendants (depth 2+) get their semantic fields
    even when intermediate parent nodes have no update entry.
    """
    children = node.get("children")
    if not isinstance(children, list):
        return
    for child in children:
        if not isinstance(child, dict):
            continue
        child_id = child.get("id")
        if child_id and child_id in children_map:
            child_update = children_map[child_id]
            if report is not None:
                report.children_updates_matched += 1
            _apply_update_fields(child, child_update, report)
        # Always recurse deeper — descendants may have updates
        _walk_children_for_updates(child, children_map, report)


def _rebuild_paths(node: Dict[str, Any], parent_path: str = "") -> None:
    """Rebuild path fields using semantic names (post-AI merge).

    After AI merge, `name` fields contain semantic names (e.g. "BottomActionBar")
    instead of Figma IDs. This rebuilds `path` using those names.
    Also deduplicates same-name siblings by adding _1, _2 suffixes.
    """
    name = node.get("name", "Component")
    current_path = f"{parent_path}/{name}" if parent_path else name
    node["path"] = current_path

    children = node.get("children")
    if isinstance(children, list):
        # Deduplicate same-name siblings
        name_counts: Dict[str, int] = {}
        name_seen: Dict[str, int] = {}
        for child in children:
            cname = child.get("name", "Component")
            name_counts[cname] = name_counts.get(cname, 0) + 1

        for child in children:
            cname = child.get("name", "Component")
            if name_counts[cname] > 1:
                idx = name_seen.get(cname, 0) + 1
                name_seen[cname] = idx
                deduped_name = f"{cname}_{idx}"
                child_path = f"{current_path}/{deduped_name}"
            else:
                child_path = f"{current_path}/{cname}"
            child["path"] = child_path
            # Recurse with the correct parent path
            _rebuild_paths_children(child, child_path)


def _rebuild_paths_children(node: Dict[str, Any], node_path: str) -> None:
    """Recursively rebuild paths for children of a node."""
    children = node.get("children")
    if not isinstance(children, list):
        return

    name_counts: Dict[str, int] = {}
    name_seen: Dict[str, int] = {}
    for child in children:
        cname = child.get("name", "Component")
        name_counts[cname] = name_counts.get(cname, 0) + 1

    for child in children:
        cname = child.get("name", "Component")
        if name_counts[cname] > 1:
            idx = name_seen.get(cname, 0) + 1
            name_seen[cname] = idx
            child_path = f"{node_path}/{cname}_{idx}"
        else:
            child_path = f"{node_path}/{cname}"
        child["path"] = child_path
        _rebuild_paths_children(child, child_path)


def _collect_all_child_ids(node: Dict[str, Any], ids: set) -> None:
    """Recursively collect all child IDs in the component tree."""
    children = node.get("children")
    if isinstance(children, list):
        for child in children:
            if isinstance(child, dict):
                child_id = child.get("id")
                if child_id:
                    ids.add(child_id)
                _collect_all_child_ids(child, ids)


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
        The dict includes a '_merge_report' key with merge statistics.
    """
    result = deepcopy(partial_spec)

    # Build lookup map from flattened children_updates
    children_updates = analyzer_output.get("children_updates", [])
    children_map = _build_children_map(children_updates)

    # Create merge report
    report = MergeReport(children_updates_total=len(children_updates))

    # Merge top-level component fields
    _merge_into_component(result, analyzer_output, children_map, report)

    # Detect unmatched children_updates (LLM returned IDs not found in tree)
    all_child_ids: set = set()
    _collect_all_child_ids(result, all_child_ids)
    for child_id in children_map:
        if child_id not in all_child_ids:
            report.children_updates_unmatched.append(child_id)

    # Log warnings for unmatched children
    if report.children_updates_unmatched:
        comp_name = result.get("name", "unknown")
        logger.warning(
            "spec_merger: component '%s' — %d/%d children_updates unmatched "
            "(IDs not found in tree): %s",
            comp_name,
            len(report.children_updates_unmatched),
            report.children_updates_total,
            report.children_updates_unmatched[:5],
        )

    # Log warnings for empty descriptions
    if report.empty_descriptions:
        comp_name = result.get("name", "unknown")
        logger.warning(
            "spec_merger: component '%s' — %d node(s) with empty description: %s",
            comp_name,
            len(report.empty_descriptions),
            report.empty_descriptions[:5],
        )

    # Rebuild paths using semantic names (post-merge)
    _rebuild_paths(result)

    # Attach report for downstream consumption
    result["_merge_report"] = report.to_dict()

    return result
