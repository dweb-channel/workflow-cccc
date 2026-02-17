"""Tests for spec_validator.py — quality validation rules."""

import pytest

from workflow.spec.spec_validator import (
    collect_merge_reports,
    run_all_validations,
    validate_bounds,
    validate_naming,
    validate_render_hints,
    validate_role_consistency,
)


# ---------------------------------------------------------------------------
# Rule 1: Parent-child role consistency
# ---------------------------------------------------------------------------


class TestRoleConsistency:
    def test_header_inside_footer_warns(self):
        node = {
            "id": "1", "name": "Footer", "path": "Footer",
            "role": "footer",
            "children": [{
                "id": "2", "name": "SubHeader", "path": "Footer/SubHeader",
                "role": "header",
            }],
        }
        warnings = []
        validate_role_consistency(node, None, warnings)
        assert len(warnings) == 1
        assert warnings[0]["rule"] == "role_parent_conflict"
        assert "header" in warnings[0]["detail"]

    def test_footer_inside_header_warns(self):
        node = {
            "id": "1", "name": "Header", "path": "Header",
            "role": "header",
            "children": [{
                "id": "2", "name": "SubFooter", "path": "Header/SubFooter",
                "role": "footer",
            }],
        }
        warnings = []
        validate_role_consistency(node, None, warnings)
        assert len(warnings) == 1
        assert warnings[0]["rule"] == "role_parent_conflict"

    def test_list_item_outside_list_warns(self):
        node = {
            "id": "1", "name": "Container", "path": "Container",
            "role": "container",
            "children": [{
                "id": "2", "name": "Item", "path": "Container/Item",
                "role": "list-item",
            }],
        }
        warnings = []
        validate_role_consistency(node, None, warnings)
        assert len(warnings) == 1
        assert warnings[0]["rule"] == "role_missing_parent"

    def test_list_item_inside_list_ok(self):
        node = {
            "id": "1", "name": "MyList", "path": "MyList",
            "role": "list",
            "children": [{
                "id": "2", "name": "Item", "path": "MyList/Item",
                "role": "list-item",
            }],
        }
        warnings = []
        validate_role_consistency(node, None, warnings)
        assert len(warnings) == 0

    def test_button_inside_button_warns(self):
        node = {
            "id": "1", "name": "OuterBtn", "path": "OuterBtn",
            "role": "button",
            "children": [{
                "id": "2", "name": "InnerBtn", "path": "OuterBtn/InnerBtn",
                "role": "button",
            }],
        }
        warnings = []
        validate_role_consistency(node, None, warnings)
        assert len(warnings) == 1
        assert warnings[0]["rule"] == "role_nested_interactive"

    def test_valid_nesting_no_warnings(self):
        node = {
            "id": "1", "name": "Header", "path": "Header",
            "role": "header",
            "children": [{
                "id": "2", "name": "Nav", "path": "Header/Nav",
                "role": "nav",
                "children": [{
                    "id": "3", "name": "Link", "path": "Header/Nav/Link",
                    "role": "button",
                }],
            }],
        }
        warnings = []
        validate_role_consistency(node, None, warnings)
        assert len(warnings) == 0


# ---------------------------------------------------------------------------
# Rule 2: Bounds overflow
# ---------------------------------------------------------------------------


class TestBoundsValidation:
    def test_child_within_parent_ok(self):
        node = {
            "id": "1", "name": "Child", "path": "Child",
            "bounds": {"x": 10, "y": 10, "width": 100, "height": 50},
        }
        parent_bounds = {"x": 0, "y": 0, "width": 200, "height": 100}
        warnings = []
        validate_bounds(node, parent_bounds, warnings)
        assert len(warnings) == 0

    def test_child_overflows_right(self):
        node = {
            "id": "1", "name": "Wide", "path": "Wide",
            "bounds": {"x": 150, "y": 0, "width": 100, "height": 50},
        }
        parent_bounds = {"x": 0, "y": 0, "width": 200, "height": 100}
        warnings = []
        validate_bounds(node, parent_bounds, warnings)
        assert len(warnings) == 1
        assert warnings[0]["rule"] == "bounds_overflow"

    def test_child_overflows_left(self):
        node = {
            "id": "1", "name": "OffLeft", "path": "OffLeft",
            "bounds": {"x": -10, "y": 0, "width": 50, "height": 50},
        }
        parent_bounds = {"x": 0, "y": 0, "width": 200, "height": 100}
        warnings = []
        validate_bounds(node, parent_bounds, warnings)
        assert len(warnings) == 1

    def test_overflow_hidden_no_warning(self):
        node = {
            "id": "1", "name": "Scrollable", "path": "Scrollable",
            "bounds": {"x": 150, "y": 0, "width": 100, "height": 50},
            "layout": {"overflow": "hidden"},
        }
        parent_bounds = {"x": 0, "y": 0, "width": 200, "height": 100}
        warnings = []
        validate_bounds(node, parent_bounds, warnings)
        assert len(warnings) == 0

    def test_tolerance_2px(self):
        node = {
            "id": "1", "name": "AlmostFit", "path": "AlmostFit",
            "bounds": {"x": 0, "y": 0, "width": 202, "height": 100},
        }
        parent_bounds = {"x": 0, "y": 0, "width": 200, "height": 100}
        warnings = []
        validate_bounds(node, parent_bounds, warnings)
        assert len(warnings) == 0  # Within 2px tolerance


# ---------------------------------------------------------------------------
# Rule 3: render_hint contradictions
# ---------------------------------------------------------------------------


class TestRenderHints:
    def test_button_spacer_warns(self):
        node = {
            "id": "1", "name": "Btn", "path": "Btn",
            "role": "button", "render_hint": "spacer",
        }
        warnings = []
        validate_render_hints(node, warnings)
        assert len(warnings) == 1
        assert warnings[0]["rule"] == "hint_role_conflict"

    def test_button_full_ok(self):
        node = {
            "id": "1", "name": "Btn", "path": "Btn",
            "role": "button", "render_hint": "full",
        }
        warnings = []
        validate_render_hints(node, warnings)
        assert len(warnings) == 0

    def test_input_platform_warns(self):
        node = {
            "id": "1", "name": "Input", "path": "Input",
            "role": "input", "render_hint": "platform",
        }
        warnings = []
        validate_render_hints(node, warnings)
        assert len(warnings) == 1

    def test_container_spacer_ok(self):
        node = {
            "id": "1", "name": "Spacer", "path": "Spacer",
            "role": "container", "render_hint": "spacer",
        }
        warnings = []
        validate_render_hints(node, warnings)
        assert len(warnings) == 0

    def test_no_hint_ok(self):
        node = {"id": "1", "name": "X", "path": "X", "role": "button"}
        warnings = []
        validate_render_hints(node, warnings)
        assert len(warnings) == 0


# ---------------------------------------------------------------------------
# Rule 4: Naming quality
# ---------------------------------------------------------------------------


class TestNamingValidation:
    def test_duplicate_names_detected(self):
        components = [
            {"id": "1", "name": "Card", "path": "Card", "role": "card",
             "description": "A card"},
            {"id": "2", "name": "Card", "path": "Card", "role": "card",
             "description": "Another card"},
            {"id": "3", "name": "Header", "path": "Header", "role": "header",
             "description": "A header"},
        ]
        report = validate_naming(components)
        assert report["duplicate_names"] == {"Card": 2}
        assert report["duplicate_rate"] > 0

    def test_empty_description_detected_for_semantic_roles(self):
        components = [
            {"id": "1", "name": "Btn", "path": "Btn", "role": "button",
             "description": ""},
            {"id": "2", "name": "Div", "path": "Div", "role": "divider",
             "description": ""},  # divider should NOT warn
        ]
        report = validate_naming(components)
        assert report["empty_description_count"] == 1
        assert report["empty_description_nodes"][0]["name"] == "Btn"

    def test_all_unique_no_duplicates(self):
        components = [
            {"id": "1", "name": "Header", "path": "Header", "role": "header",
             "description": "Page header"},
            {"id": "2", "name": "Footer", "path": "Footer", "role": "footer",
             "description": "Page footer"},
        ]
        report = validate_naming(components)
        assert report["duplicate_rate"] == 0.0
        assert report["empty_description_count"] == 0


# ---------------------------------------------------------------------------
# Merge report aggregation
# ---------------------------------------------------------------------------


class TestMergeReports:
    def test_collect_and_remove_internal_key(self):
        components = [
            {"id": "1", "name": "A", "_merge_report": {
                "children_updates_total": 5,
                "children_updates_matched": 3,
                "children_updates_unmatched": ["x1", "x2"],
                "children_updates_loss_rate": 0.4,
                "empty_descriptions": [],
            }},
            {"id": "2", "name": "B", "_merge_report": {
                "children_updates_total": 3,
                "children_updates_matched": 3,
                "children_updates_unmatched": [],
                "children_updates_loss_rate": 0.0,
                "empty_descriptions": [],
            }},
        ]
        result = collect_merge_reports(components)
        assert result["children_updates_total"] == 8
        assert result["children_updates_matched"] == 6
        assert result["children_updates_unmatched_count"] == 2
        assert result["children_updates_loss_rate"] == 0.25
        # Internal key removed
        assert "_merge_report" not in components[0]
        assert "_merge_report" not in components[1]

    def test_no_merge_reports_zeroed(self):
        components = [{"id": "1", "name": "A"}]
        result = collect_merge_reports(components)
        assert result["children_updates_total"] == 0
        assert result["children_updates_loss_rate"] == 0.0


# ---------------------------------------------------------------------------
# Integration: run_all_validations
# ---------------------------------------------------------------------------


class TestRunAllValidations:
    def test_returns_complete_report(self):
        components = [
            {
                "id": "1", "name": "Page", "path": "Page",
                "role": "page", "description": "Main page",
                "bounds": {"x": 0, "y": 0, "width": 393, "height": 852},
                "children": [{
                    "id": "2", "name": "Header", "path": "Page/Header",
                    "role": "header", "description": "Top bar",
                    "bounds": {"x": 0, "y": 0, "width": 393, "height": 60},
                }],
            },
        ]
        page = {"device": {"width": 393, "height": 852}}
        result = run_all_validations(components, page, node_id="test")

        assert "quality_warnings" in result
        assert "quality_warning_count" in result
        assert "naming" in result
        assert "merge_stats" in result
        assert isinstance(result["quality_warnings"], list)
        assert result["quality_warning_count"] == 0
