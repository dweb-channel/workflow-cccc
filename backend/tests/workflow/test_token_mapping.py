"""Tests for token reverse mapping utility."""

import json
from pathlib import Path

import pytest

from workflow.spec.token_mapping import (
    apply_token_reverse_map,
    build_color_token_map,
    build_spacing_token_map,
)

SPEC_DIR = Path(__file__).resolve().parents[2] / "workflow" / "spec"


@pytest.fixture
def design_tokens():
    return {
        "colors": {
            "brand-primary": "#FF6B35",
            "background-dark": "#1A1A1A",
            "text-primary": "#FFFFFF",
            "text-secondary": "#FFFFFFB3",
            "surface-overlay": "#00000040",
        },
        "spacing": {
            "xs": 4,
            "sm": 8,
            "md": 16,
            "lg": 24,
        },
    }


@pytest.fixture
def color_map(design_tokens):
    return build_color_token_map(design_tokens)


@pytest.fixture
def spacing_map(design_tokens):
    return build_spacing_token_map(design_tokens)


@pytest.fixture
def example_spec():
    with open(SPEC_DIR / "example_spec.json") as f:
        return json.load(f)


# ── build_color_token_map ──


class TestBuildColorTokenMap:
    def test_builds_reverse_map(self, design_tokens):
        result = build_color_token_map(design_tokens)
        assert result["#FF6B35"] == "brand-primary"
        assert result["#FFFFFF"] == "text-primary"
        assert result["#FFFFFFB3"] == "text-secondary"

    def test_case_insensitive_keys(self, design_tokens):
        design_tokens["colors"]["test"] = "#aabbcc"
        result = build_color_token_map(design_tokens)
        assert result["#AABBCC"] == "test"

    def test_empty_tokens(self):
        assert build_color_token_map({}) == {}
        assert build_color_token_map({"colors": {}}) == {}

    def test_skips_non_string_values(self):
        result = build_color_token_map({"colors": {"bad": 123, "good": "#FFF"}})
        assert "#FFF" in result
        assert len(result) == 1


# ── build_spacing_token_map ──


class TestBuildSpacingTokenMap:
    def test_builds_reverse_map(self, design_tokens):
        result = build_spacing_token_map(design_tokens)
        assert result[4] == "xs"
        assert result[8] == "sm"
        assert result[16] == "md"
        assert result[24] == "lg"

    def test_empty_tokens(self):
        assert build_spacing_token_map({}) == {}
        assert build_spacing_token_map({"spacing": {}}) == {}

    def test_skips_non_numeric_values(self):
        result = build_spacing_token_map({"spacing": {"bad": "16px", "good": 16}})
        assert result[16] == "good"
        assert len(result) == 1


# ── Color mapping (T1) ──


class TestColorMapping:
    def test_bare_string_with_token_match(self, color_map):
        spec = {
            "style": {"background": {"type": "solid", "color": "#FF6B35"}},
        }
        result = apply_token_reverse_map(spec, color_map)
        assert result["style"]["background"]["color"] == {
            "value": "#FF6B35",
            "token": "brand-primary",
        }

    def test_bare_string_without_token_match(self, color_map):
        spec = {
            "style": {"background": {"type": "solid", "color": "#FF8F5E"}},
        }
        result = apply_token_reverse_map(spec, color_map)
        assert result["style"]["background"]["color"] == {"value": "#FF8F5E"}

    def test_existing_object_with_token(self, color_map):
        spec = {
            "style": {
                "background": {
                    "type": "solid",
                    "color": {"value": "#FF6B35", "token": "brand-primary"},
                }
            },
        }
        result = apply_token_reverse_map(spec, color_map)
        assert result["style"]["background"]["color"] == {
            "value": "#FF6B35",
            "token": "brand-primary",
        }

    def test_existing_object_without_token_adds_match(self, color_map):
        spec = {
            "style": {
                "background": {"type": "solid", "color": {"value": "#FF6B35"}}
            },
        }
        result = apply_token_reverse_map(spec, color_map)
        assert result["style"]["background"]["color"] == {
            "value": "#FF6B35",
            "token": "brand-primary",
        }

    def test_null_color_unchanged(self, color_map):
        spec = {"style": {"background": {"type": "none"}}}
        result = apply_token_reverse_map(spec, color_map)
        assert "color" not in result["style"]["background"]

    def test_gradient_stops_colors(self, color_map):
        spec = {
            "style": {
                "background": {
                    "type": "gradient-linear",
                    "gradient": {
                        "angle": 180,
                        "stops": [
                            {"color": "#00000000", "position": 0.0},
                            {"color": "#000000CC", "position": 1.0},
                        ],
                    },
                }
            },
        }
        result = apply_token_reverse_map(spec, color_map)
        stops = result["style"]["background"]["gradient"]["stops"]
        assert stops[0]["color"] == {"value": "#00000000"}
        assert stops[1]["color"] == {"value": "#000000CC"}

    def test_border_color(self, color_map):
        spec = {
            "style": {"border": {"width": 1, "color": "#FFFFFF", "style": "solid"}},
        }
        result = apply_token_reverse_map(spec, color_map)
        assert result["style"]["border"]["color"] == {
            "value": "#FFFFFF",
            "token": "text-primary",
        }

    def test_shadow_color(self, color_map):
        spec = {
            "style": {
                "shadow": [
                    {
                        "type": "drop",
                        "x": 0,
                        "y": 2,
                        "blur": 8,
                        "spread": 0,
                        "color": "#FF6B3540",
                    }
                ]
            },
        }
        result = apply_token_reverse_map(spec, color_map)
        assert result["style"]["shadow"][0]["color"] == {"value": "#FF6B3540"}

    def test_typography_color(self, color_map):
        spec = {
            "style": {},
            "typography": {"content": "hello", "color": "#FFFFFF"},
        }
        result = apply_token_reverse_map(spec, color_map)
        assert result["typography"]["color"] == {
            "value": "#FFFFFF",
            "token": "text-primary",
        }

    def test_icon_color(self, color_map):
        spec = {
            "style": {},
            "content": {"icon": {"name": "close", "size": 24, "color": "#FFFFFF"}},
        }
        result = apply_token_reverse_map(spec, color_map)
        assert result["content"]["icon"]["color"] == {
            "value": "#FFFFFF",
            "token": "text-primary",
        }

    def test_8char_hex_with_alpha_token_match(self, color_map):
        spec = {
            "style": {},
            "typography": {"content": "sub", "color": "#FFFFFFB3"},
        }
        result = apply_token_reverse_map(spec, color_map)
        assert result["typography"]["color"] == {
            "value": "#FFFFFFB3",
            "token": "text-secondary",
        }

    def test_case_insensitive_matching(self, color_map):
        spec = {
            "style": {},
            "typography": {"content": "test", "color": "#ff6b35"},
        }
        result = apply_token_reverse_map(spec, color_map)
        assert result["typography"]["color"] == {
            "value": "#ff6b35",
            "token": "brand-primary",
        }


# ── Children recursion ──


class TestChildrenRecursion:
    def test_processes_nested_children(self, color_map):
        spec = {
            "style": {},
            "children": [
                {
                    "style": {},
                    "typography": {"content": "child", "color": "#FF6B35"},
                    "children": [
                        {
                            "style": {},
                            "content": {
                                "icon": {"name": "x", "size": 16, "color": "#FFFFFF"}
                            },
                        }
                    ],
                }
            ],
        }
        result = apply_token_reverse_map(spec, color_map)
        child = result["children"][0]
        assert child["typography"]["color"]["token"] == "brand-primary"
        grandchild = child["children"][0]
        assert grandchild["content"]["icon"]["color"]["token"] == "text-primary"

    def test_empty_children_no_error(self, color_map):
        spec = {"style": {}, "children": []}
        result = apply_token_reverse_map(spec, color_map)
        assert result["children"] == []


# ── Interaction states style_overrides ──


class TestInteractionStateOverrides:
    def test_hover_background_color(self, color_map):
        spec = {
            "style": {},
            "interaction": {
                "states": [
                    {
                        "name": "hover",
                        "style_overrides": {
                            "background": {"type": "solid", "color": "#FF8F5E"}
                        },
                    }
                ]
            },
        }
        result = apply_token_reverse_map(spec, color_map)
        hover_color = result["interaction"]["states"][0]["style_overrides"][
            "background"
        ]["color"]
        assert hover_color == {"value": "#FF8F5E"}

    def test_state_override_shadow_color(self, color_map):
        spec = {
            "style": {},
            "interaction": {
                "states": [
                    {
                        "name": "hover",
                        "style_overrides": {
                            "shadow": [
                                {
                                    "type": "drop",
                                    "x": 0,
                                    "y": 4,
                                    "blur": 12,
                                    "spread": 0,
                                    "color": "#FF6B35",
                                }
                            ]
                        },
                    }
                ]
            },
        }
        result = apply_token_reverse_map(spec, color_map)
        shadow_color = result["interaction"]["states"][0]["style_overrides"]["shadow"][
            0
        ]["color"]
        assert shadow_color == {"value": "#FF6B35", "token": "brand-primary"}

    def test_no_interaction_no_error(self, color_map):
        spec = {"style": {}}
        result = apply_token_reverse_map(spec, color_map)
        assert "interaction" not in result

    def test_empty_states_no_error(self, color_map):
        spec = {"style": {}, "interaction": {"states": []}}
        result = apply_token_reverse_map(spec, color_map)
        assert result["interaction"]["states"] == []


# ── Spacing mapping (T3) ──


class TestSpacingMapping:
    def test_gap_with_token_match(self, color_map, spacing_map):
        spec = {"style": {}, "layout": {"type": "flex", "gap": 16}}
        result = apply_token_reverse_map(spec, color_map, spacing_map)
        assert result["layout"]["gap"] == {"value": 16, "token": "md"}

    def test_gap_without_token_match(self, color_map, spacing_map):
        spec = {"style": {}, "layout": {"type": "flex", "gap": 12}}
        result = apply_token_reverse_map(spec, color_map, spacing_map)
        assert result["layout"]["gap"] == {"value": 12}

    def test_gap_zero(self, color_map, spacing_map):
        spec = {"style": {}, "layout": {"type": "flex", "gap": 0}}
        result = apply_token_reverse_map(spec, color_map, spacing_map)
        assert result["layout"]["gap"] == {"value": 0}

    def test_padding_with_mixed_tokens(self, color_map, spacing_map):
        spec = {"style": {}, "layout": {"type": "flex", "padding": [14, 24, 0, 24]}}
        result = apply_token_reverse_map(spec, color_map, spacing_map)
        padding = result["layout"]["padding"]
        assert padding[0] == {"value": 14}  # no token
        assert padding[1] == {"value": 24, "token": "lg"}
        assert padding[2] == {"value": 0}
        assert padding[3] == {"value": 24, "token": "lg"}

    def test_padding_all_tokens(self, color_map, spacing_map):
        spec = {"style": {}, "layout": {"type": "flex", "padding": [8, 16, 8, 16]}}
        result = apply_token_reverse_map(spec, color_map, spacing_map)
        padding = result["layout"]["padding"]
        assert padding[0] == {"value": 8, "token": "sm"}
        assert padding[1] == {"value": 16, "token": "md"}
        assert padding[2] == {"value": 8, "token": "sm"}
        assert padding[3] == {"value": 16, "token": "md"}

    def test_spacing_skipped_when_no_map(self, color_map):
        spec = {"style": {}, "layout": {"type": "flex", "gap": 16, "padding": [8, 8, 8, 8]}}
        result = apply_token_reverse_map(spec, color_map)  # no spacing_map
        assert result["layout"]["gap"] == 16  # unchanged
        assert result["layout"]["padding"] == [8, 8, 8, 8]  # unchanged

    def test_spacing_in_children(self, color_map, spacing_map):
        spec = {
            "style": {},
            "layout": {"type": "flex", "gap": 0},
            "children": [
                {
                    "style": {},
                    "layout": {"type": "flex", "gap": 8, "padding": [0, 16, 0, 16]},
                }
            ],
        }
        result = apply_token_reverse_map(spec, color_map, spacing_map)
        child_layout = result["children"][0]["layout"]
        assert child_layout["gap"] == {"value": 8, "token": "sm"}
        assert child_layout["padding"][1] == {"value": 16, "token": "md"}


# ── Full document mode ──


class TestFullDocument:
    def test_processes_components_array(self, color_map):
        doc = {
            "version": "1.0",
            "components": [
                {
                    "id": "1",
                    "style": {},
                    "typography": {"content": "test", "color": "#FF6B35"},
                },
                {
                    "id": "2",
                    "style": {"background": {"type": "solid", "color": "#FFFFFF"}},
                },
            ],
        }
        result = apply_token_reverse_map(doc, color_map)
        assert result["components"][0]["typography"]["color"]["token"] == "brand-primary"
        assert result["components"][1]["style"]["background"]["color"]["token"] == "text-primary"

    def test_does_not_mutate_original(self, color_map):
        spec = {
            "style": {},
            "typography": {"content": "test", "color": "#FF6B35"},
        }
        original_color = spec["typography"]["color"]
        apply_token_reverse_map(spec, color_map)
        assert spec["typography"]["color"] == original_color  # unchanged

    def test_example_spec_integration(self, example_spec, color_map, spacing_map):
        """Verify against the real example_spec.json."""
        result = apply_token_reverse_map(example_spec, color_map, spacing_map)

        # HeroImage (index 0) has no colors to map in style
        hero = result["components"][0]
        assert hero["name"] == "HeroImage"

        # TopNavBar (index 1) -> children -> NavContent -> children -> BackIcon
        nav = result["components"][1]
        assert nav["name"] == "TopNavBar"

        # StatusBar typography.color (bare "#FFFFFF" in example)
        status_bar = nav["children"][0]
        assert status_bar["name"] == "StatusBar"
        assert status_bar["typography"]["color"] == {
            "value": "#FFFFFF",
            "token": "text-primary",
        }

        # BackIcon content.icon.color (already object in example)
        nav_content = nav["children"][1]
        back_icon = nav_content["children"][0]
        assert back_icon["content"]["icon"]["color"] == {
            "value": "#FFFFFF",
            "token": "text-primary",
        }

        # TitleCN typography.color (already object in example)
        title_group = nav_content["children"][1]
        title_cn = title_group["children"][0]
        assert title_cn["typography"]["color"] == {
            "value": "#FFFFFF",
            "token": "text-primary",
        }

        # SubtitleEN typography.color with alpha
        subtitle = title_group["children"][1]
        assert subtitle["typography"]["color"] == {
            "value": "#FFFFFFB3",
            "token": "text-secondary",
        }

        # BottomActionBar (index 2)
        bottom = result["components"][2]
        assert bottom["name"] == "BottomActionBar"

        # Gradient stops (bare hex, no token)
        stops = bottom["style"]["background"]["gradient"]["stops"]
        assert stops[0]["color"] == {"value": "#00000000"}
        assert stops[1]["color"] == {"value": "#000000CC"}

        # CTAButton
        cta = bottom["children"][1]
        assert cta["name"] == "CTAButton"

        # CTA background color (already object with token)
        assert cta["style"]["background"]["color"] == {
            "value": "#FF6B35",
            "token": "brand-primary",
        }

        # CTA shadow color (object without token)
        assert cta["style"]["shadow"][0]["color"] == {"value": "#FF6B3540"}

        # CTA typography color
        assert cta["typography"]["color"] == {
            "value": "#FFFFFF",
            "token": "text-primary",
        }

        # CTA hover state background color (object, no token match)
        hover_state = cta["interaction"]["states"][0]
        assert hover_state["name"] == "hover"
        assert hover_state["style_overrides"]["background"]["color"] == {
            "value": "#FF8F5E",
        }

        # Spacing: NavContent padding [0, 16, 0, 16]
        nav_content_padding = nav_content["layout"]["padding"]
        assert nav_content_padding[0] == {"value": 0}
        assert nav_content_padding[1] == {"value": 16, "token": "md"}
        assert nav_content_padding[2] == {"value": 0}
        assert nav_content_padding[3] == {"value": 16, "token": "md"}

        # Spacing: StatusBar padding [14, 24, 0, 24]
        sb_padding = status_bar["layout"]["padding"]
        assert sb_padding[0] == {"value": 14}  # no token
        assert sb_padding[1] == {"value": 24, "token": "lg"}


# ── Edge cases ──


class TestEdgeCases:
    def test_empty_spec(self, color_map):
        result = apply_token_reverse_map({}, color_map)
        assert result == {}

    def test_empty_style(self, color_map):
        result = apply_token_reverse_map({"style": {}}, color_map)
        assert result == {"style": {}}

    def test_no_style_key(self, color_map):
        result = apply_token_reverse_map({"id": "1", "name": "Test"}, color_map)
        assert result == {"id": "1", "name": "Test"}

    def test_empty_color_map(self):
        spec = {
            "style": {},
            "typography": {"content": "test", "color": "#FF6B35"},
        }
        result = apply_token_reverse_map(spec, {})
        assert result["typography"]["color"] == {"value": "#FF6B35"}

    def test_non_color_string_in_style_unchanged(self, color_map):
        spec = {"style": {"background": {"type": "none"}}}
        result = apply_token_reverse_map(spec, color_map)
        assert result["style"]["background"]["type"] == "none"

    def test_deeply_nested_children(self, color_map):
        spec = {
            "style": {},
            "children": [
                {
                    "style": {},
                    "children": [
                        {
                            "style": {},
                            "children": [
                                {
                                    "style": {},
                                    "typography": {
                                        "content": "deep",
                                        "color": "#FF6B35",
                                    },
                                }
                            ],
                        }
                    ],
                }
            ],
        }
        result = apply_token_reverse_map(spec, color_map)
        deep = result["children"][0]["children"][0]["children"][0]
        assert deep["typography"]["color"]["token"] == "brand-primary"
