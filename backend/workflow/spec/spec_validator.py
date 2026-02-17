"""Spec quality validation rules (pure Python, zero LLM cost).

Called by SpecAssemblerNode after merge to detect quality issues:
- Parent-child role conflicts
- Bounds overflow
- render_hint contradictions
- Naming quality (duplicates, empty descriptions)
- Merge report aggregation
"""

from __future__ import annotations

import logging
from collections import Counter
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Rule definitions
# ---------------------------------------------------------------------------

# Child role -> set of forbidden parent roles
_ROLE_PARENT_CONFLICTS = {
    "header": {"footer"},
    "footer": {"header"},
}

# Child role -> set of required parent roles
_ROLE_REQUIRES_PARENT = {
    "list-item": {"list"},
}

# Role -> set of contradictory render_hints
_HINT_ROLE_CONFLICTS = {
    "button": {"spacer", "platform"},
    "input": {"spacer", "platform"},
    "nav": {"spacer", "platform"},
}

_INTERACTIVE_ROLES = {"button", "input"}


# ---------------------------------------------------------------------------
# Validation functions
# ---------------------------------------------------------------------------

def validate_role_consistency(
    node: Dict[str, Any],
    parent_role: Optional[str],
    warnings: List[Dict[str, Any]],
) -> None:
    """Check parent-child role conflicts recursively."""
    role = node.get("role", "other")
    node_ref = {
        "id": node.get("id", ""),
        "name": node.get("name", ""),
        "path": node.get("path", ""),
    }

    # Forbidden parent roles
    forbidden_parents = _ROLE_PARENT_CONFLICTS.get(role)
    if forbidden_parents and parent_role in forbidden_parents:
        warnings.append({
            **node_ref,
            "rule": "role_parent_conflict",
            "detail": f"role='{role}' nested inside parent role='{parent_role}'",
        })

    # Required parent roles
    required_parents = _ROLE_REQUIRES_PARENT.get(role)
    if required_parents and parent_role not in required_parents:
        warnings.append({
            **node_ref,
            "rule": "role_missing_parent",
            "detail": (
                f"role='{role}' requires parent role in "
                f"{required_parents}, got '{parent_role}'"
            ),
        })

    # Nested same interactive role (e.g., button inside button)
    if role in _INTERACTIVE_ROLES and role == parent_role:
        warnings.append({
            **node_ref,
            "rule": "role_nested_interactive",
            "detail": f"role='{role}' nested inside same role='{parent_role}'",
        })

    for child in node.get("children", []):
        if isinstance(child, dict):
            validate_role_consistency(child, role, warnings)


def validate_bounds(
    node: Dict[str, Any],
    parent_bounds: Optional[Dict[str, Any]],
    warnings: List[Dict[str, Any]],
) -> None:
    """Check if child bounds exceed parent bounds (2px tolerance)."""
    bounds = node.get("bounds")
    if not isinstance(bounds, dict) or not isinstance(parent_bounds, dict):
        for child in node.get("children", []):
            if isinstance(child, dict):
                validate_bounds(child, bounds, warnings)
        return

    tolerance = 2
    px, py = parent_bounds.get("x", 0), parent_bounds.get("y", 0)
    pw, ph = parent_bounds.get("width", 0), parent_bounds.get("height", 0)
    cx, cy = bounds.get("x", 0), bounds.get("y", 0)
    cw, ch = bounds.get("width", 0), bounds.get("height", 0)

    overflow = (
        cx + tolerance < px
        or cy + tolerance < py
        or cx + cw > px + pw + tolerance
        or cy + ch > py + ph + tolerance
    )

    if overflow and cw > 0 and ch > 0:
        layout = node.get("layout", {})
        if layout.get("overflow") not in ("hidden", "scroll"):
            warnings.append({
                "id": node.get("id", ""),
                "name": node.get("name", ""),
                "path": node.get("path", ""),
                "rule": "bounds_overflow",
                "detail": (
                    f"bounds ({cx},{cy},{cw}x{ch}) exceeds "
                    f"parent ({px},{py},{pw}x{ph})"
                ),
            })

    for child in node.get("children", []):
        if isinstance(child, dict):
            validate_bounds(child, bounds, warnings)


def validate_render_hints(
    node: Dict[str, Any],
    warnings: List[Dict[str, Any]],
) -> None:
    """Detect contradictory role + render_hint combinations."""
    role = node.get("role", "other")
    hint = node.get("render_hint")
    if hint:
        forbidden = _HINT_ROLE_CONFLICTS.get(role, set())
        if hint in forbidden:
            warnings.append({
                "id": node.get("id", ""),
                "name": node.get("name", ""),
                "path": node.get("path", ""),
                "rule": "hint_role_conflict",
                "detail": f"role='{role}' with render_hint='{hint}' is contradictory",
            })
    for child in node.get("children", []):
        if isinstance(child, dict):
            validate_render_hints(child, warnings)


def validate_naming(
    components: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Check naming quality: duplicates and empty descriptions."""
    all_names: List[str] = []
    empty_desc_nodes: List[Dict[str, Any]] = []

    def _collect(node: Dict[str, Any]) -> None:
        name = node.get("name", "")
        if name:
            all_names.append(name)
        desc = node.get("description", "")
        if not desc or (isinstance(desc, str) and not desc.strip()):
            role = node.get("role", "other")
            # Only warn for semantic roles (skip decorative/divider/other)
            if role not in ("decorative", "divider", "other"):
                empty_desc_nodes.append({
                    "id": node.get("id", ""),
                    "name": node.get("name", ""),
                    "path": node.get("path", ""),
                    "role": role,
                })
        for child in node.get("children", []):
            if isinstance(child, dict):
                _collect(child)

    for comp in components:
        _collect(comp)

    name_counts = Counter(all_names)
    duplicates = {n: c for n, c in name_counts.items() if c > 1}
    duplicate_rate = len(duplicates) / max(len(name_counts), 1)

    return {
        "total_names": len(all_names),
        "unique_names": len(name_counts),
        "duplicate_names": duplicates,
        "duplicate_rate": round(duplicate_rate, 2),
        "empty_description_count": len(empty_desc_nodes),
        "empty_description_nodes": empty_desc_nodes[:10],
    }


def collect_merge_reports(
    components: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Aggregate _merge_report from all components (removes internal key)."""
    total_updates = 0
    total_matched = 0
    all_unmatched: List[str] = []

    for comp in components:
        report = comp.pop("_merge_report", None)
        if isinstance(report, dict):
            total_updates += report.get("children_updates_total", 0)
            total_matched += report.get("children_updates_matched", 0)
            all_unmatched.extend(report.get("children_updates_unmatched", []))

    loss_rate = (
        len(all_unmatched) / total_updates if total_updates > 0 else 0.0
    )
    return {
        "children_updates_total": total_updates,
        "children_updates_matched": total_matched,
        "children_updates_unmatched_count": len(all_unmatched),
        "children_updates_loss_rate": round(loss_rate, 2),
    }


# ---------------------------------------------------------------------------
# Main entry point — run all validations
# ---------------------------------------------------------------------------

def run_all_validations(
    components: List[Dict[str, Any]],
    page: Dict[str, Any],
    node_id: str = "",
) -> Dict[str, Any]:
    """Run all quality validation rules on assembled components.

    Returns a validation report dict to embed in spec_document.validation.
    """
    # Collect merge reports first (pops _merge_report from components)
    merge_stats = collect_merge_reports(components)
    if merge_stats["children_updates_unmatched_count"] > 0:
        logger.warning(
            "SpecValidator [%s]: %d/%d children_updates unmatched "
            "(loss_rate=%.0f%%)",
            node_id,
            merge_stats["children_updates_unmatched_count"],
            merge_stats["children_updates_total"],
            merge_stats["children_updates_loss_rate"] * 100,
        )

    # Quality warnings
    quality_warnings: List[Dict[str, Any]] = []

    for comp in components:
        validate_role_consistency(comp, None, quality_warnings)

    for comp in components:
        page_device = page.get("device")
        parent_bounds = None
        if page_device:
            parent_bounds = {
                "x": 0, "y": 0,
                "width": page_device.get("width", 9999),
                "height": page_device.get("height", 99999),
            }
        validate_bounds(comp, parent_bounds, quality_warnings)

    for comp in components:
        validate_render_hints(comp, quality_warnings)

    naming_report = validate_naming(components)

    # Log summary
    if quality_warnings:
        logger.warning(
            "SpecValidator [%s]: %d quality warning(s)",
            node_id, len(quality_warnings),
        )
        for w in quality_warnings[:5]:
            logger.warning(
                "  [%s] %s: %s",
                w.get("rule"), w.get("name"), w.get("detail"),
            )

    if naming_report["duplicate_rate"] > 0.3:
        logger.warning(
            "SpecValidator [%s]: high name duplicate rate %.0f%%",
            node_id, naming_report["duplicate_rate"] * 100,
        )

    if naming_report["empty_description_count"] > 0:
        logger.warning(
            "SpecValidator [%s]: %d node(s) with empty description",
            node_id, naming_report["empty_description_count"],
        )

    return {
        "quality_warnings": quality_warnings,
        "quality_warning_count": len(quality_warnings),
        "naming": naming_report,
        "merge_stats": merge_stats,
    }
