"""Tests for spec merger utility."""

import json
from pathlib import Path

import pytest

from workflow.spec.spec_merger import merge_analyzer_output

SPEC_DIR = Path(__file__).resolve().parents[2] / "workflow" / "spec"


@pytest.fixture
def example_spec():
    with open(SPEC_DIR / "example_spec.json") as f:
        return json.load(f)


@pytest.fixture
def test_cases():
    with open(SPEC_DIR / "spec_analyzer_test_cases.json") as f:
        return json.load(f)


# ── Basic field merging ──


class TestBasicMerge:
    def test_merges_role(self):
        partial = {"id": "1", "style": {}}
        output = {"role": "button", "description": "A button"}
        result = merge_analyzer_output(partial, output)
        assert result["role"] == "button"

    def test_merges_description(self):
        partial = {"id": "1", "style": {}}
        output = {"role": "text", "description": "Primary title text"}
        result = merge_analyzer_output(partial, output)
        assert result["description"] == "Primary title text"

    def test_merges_render_hint(self):
        partial = {"id": "1", "style": {}}
        output = {"role": "container", "description": "Spacer", "render_hint": "spacer"}
        result = merge_analyzer_output(partial, output)
        assert result["render_hint"] == "spacer"

    def test_null_render_hint_not_written(self):
        partial = {"id": "1", "style": {}}
        output = {"role": "button", "description": "CTA", "render_hint": None}
        result = merge_analyzer_output(partial, output)
        assert "render_hint" not in result

    def test_preserves_existing_fields(self):
        partial = {
            "id": "1",
            "name": "TestButton",
            "bounds": {"x": 0, "y": 0, "width": 100, "height": 40},
            "layout": {"type": "flex", "direction": "row"},
            "sizing": {"width": "hug", "height": "40px"},
            "style": {"background": {"type": "solid", "color": "#FF6B35"}},
            "typography": {"content": "Click me", "font_size": 14},
        }
        output = {"role": "button", "description": "Action button"}
        result = merge_analyzer_output(partial, output)
        assert result["name"] == "TestButton"
        assert result["bounds"] == {"x": 0, "y": 0, "width": 100, "height": 40}
        assert result["layout"] == {"type": "flex", "direction": "row"}
        assert result["style"]["background"]["color"] == "#FF6B35"
        assert result["typography"]["content"] == "Click me"

    def test_does_not_mutate_input(self):
        partial = {"id": "1", "style": {}}
        output = {"role": "button", "description": "CTA"}
        merge_analyzer_output(partial, output)
        assert "role" not in partial
        assert "description" not in partial


# ── Content updates ──


class TestContentUpdates:
    def test_merges_image_alt(self):
        partial = {
            "id": "1",
            "style": {},
            "content": {"image": {"src": "img.png", "fit": "cover"}},
        }
        output = {
            "role": "image",
            "description": "Hero image",
            "content_updates": {"image_alt": "A decorative photo", "icon_name": None},
        }
        result = merge_analyzer_output(partial, output)
        assert result["content"]["image"]["alt"] == "A decorative photo"
        assert result["content"]["image"]["src"] == "img.png"  # preserved

    def test_merges_icon_name(self):
        partial = {
            "id": "1",
            "style": {},
            "content": {"icon": {"name": "unnamed", "size": 24, "color": "#FFF"}},
        }
        output = {
            "role": "icon",
            "description": "Close icon",
            "content_updates": {"image_alt": None, "icon_name": "close"},
        }
        result = merge_analyzer_output(partial, output)
        assert result["content"]["icon"]["name"] == "close"
        assert result["content"]["icon"]["size"] == 24  # preserved

    def test_null_content_updates_no_change(self):
        partial = {
            "id": "1",
            "style": {},
            "content": {"icon": {"name": "original", "size": 24}},
        }
        output = {
            "role": "icon",
            "description": "An icon",
            "content_updates": {"image_alt": None, "icon_name": None},
        }
        result = merge_analyzer_output(partial, output)
        assert result["content"]["icon"]["name"] == "original"

    def test_no_content_in_partial_no_error(self):
        partial = {"id": "1", "style": {}}
        output = {
            "role": "text",
            "description": "Text element",
            "content_updates": {"image_alt": "test", "icon_name": "test"},
        }
        result = merge_analyzer_output(partial, output)
        assert "content" not in result


# ── Interaction merging ──


class TestInteractionMerge:
    def test_merges_behaviors(self):
        partial = {"id": "1", "style": {}}
        output = {
            "role": "button",
            "description": "CTA",
            "interaction": {
                "behaviors": [
                    {"trigger": "click", "action": "Navigate to page", "target": "page"}
                ],
                "states": [],
            },
        }
        result = merge_analyzer_output(partial, output)
        assert len(result["interaction"]["behaviors"]) == 1
        assert result["interaction"]["behaviors"][0]["trigger"] == "click"

    def test_merges_llm_states_with_node1_overrides(self):
        partial = {
            "id": "1",
            "style": {},
            "interaction": {
                "states": [
                    {
                        "name": "hover",
                        "style_overrides": {
                            "background": {"type": "solid", "color": "#FF8F5E"}
                        },
                    },
                    {
                        "name": "active",
                        "style_overrides": {"opacity": 0.8},
                    },
                ],
                "transitions": [
                    {"property": "background-color", "duration_ms": 150, "easing": "ease-out"}
                ],
            },
        }
        output = {
            "role": "button",
            "description": "CTA",
            "interaction": {
                "behaviors": [
                    {"trigger": "click", "action": "Navigate", "target": "page"}
                ],
                "states": [
                    {"name": "hover", "description": "Lighter orange on hover"},
                    {"name": "active", "description": "Dimmed when pressed"},
                ],
            },
        }
        result = merge_analyzer_output(partial, output)
        states = result["interaction"]["states"]

        # hover: merged — has both style_overrides (from Node 1) and description (from LLM)
        hover = next(s for s in states if s["name"] == "hover")
        assert hover["description"] == "Lighter orange on hover"
        assert hover["style_overrides"]["background"]["color"] == "#FF8F5E"

        # active: merged
        active = next(s for s in states if s["name"] == "active")
        assert active["description"] == "Dimmed when pressed"
        assert active["style_overrides"]["opacity"] == 0.8

        # transitions preserved from Node 1
        assert result["interaction"]["transitions"][0]["duration_ms"] == 150

    def test_llm_adds_new_state(self):
        partial = {
            "id": "1",
            "style": {},
            "interaction": {
                "states": [
                    {"name": "hover", "style_overrides": {"opacity": 0.9}},
                ],
            },
        }
        output = {
            "role": "button",
            "description": "CTA",
            "interaction": {
                "behaviors": [],
                "states": [
                    {"name": "hover", "description": "Hover effect"},
                    {"name": "disabled", "description": "Greyed out when inactive"},
                ],
            },
        }
        result = merge_analyzer_output(partial, output)
        states = result["interaction"]["states"]
        assert len(states) == 2
        names = [s["name"] for s in states]
        assert "hover" in names
        assert "disabled" in names

    def test_node1_states_preserved_if_llm_doesnt_mention(self):
        partial = {
            "id": "1",
            "style": {},
            "interaction": {
                "states": [
                    {"name": "hover", "style_overrides": {"opacity": 0.9}},
                    {"name": "focus", "style_overrides": {"border": {"width": 2}}},
                ],
            },
        }
        output = {
            "role": "button",
            "description": "CTA",
            "interaction": {
                "behaviors": [],
                "states": [
                    {"name": "hover", "description": "Lighter on hover"},
                ],
            },
        }
        result = merge_analyzer_output(partial, output)
        states = result["interaction"]["states"]
        assert len(states) == 2
        focus = next(s for s in states if s["name"] == "focus")
        assert focus["style_overrides"]["border"]["width"] == 2

    def test_no_existing_interaction(self):
        partial = {"id": "1", "style": {}}
        output = {
            "role": "icon",
            "description": "Back icon",
            "interaction": {
                "behaviors": [
                    {"trigger": "click", "action": "Go back", "target": "page"}
                ],
                "states": [],
            },
        }
        result = merge_analyzer_output(partial, output)
        assert result["interaction"]["behaviors"][0]["action"] == "Go back"

    def test_empty_interaction_no_error(self):
        partial = {"id": "1", "style": {}}
        output = {"role": "text", "description": "Label"}
        result = merge_analyzer_output(partial, output)
        assert "interaction" not in result


# ── Children updates (flattened → recursive merge) ──


class TestChildrenUpdates:
    def test_merges_direct_children(self):
        partial = {
            "id": "root",
            "style": {},
            "children": [
                {"id": "child-1", "style": {}},
                {"id": "child-2", "style": {}},
            ],
        }
        output = {
            "role": "container",
            "description": "Root",
            "children_updates": [
                {"id": "child-1", "role": "text", "description": "Title"},
                {"id": "child-2", "role": "icon", "description": "Arrow"},
            ],
        }
        result = merge_analyzer_output(partial, output)
        assert result["children"][0]["role"] == "text"
        assert result["children"][0]["description"] == "Title"
        assert result["children"][1]["role"] == "icon"
        assert result["children"][1]["description"] == "Arrow"

    def test_merges_deeply_nested_children(self):
        partial = {
            "id": "root",
            "style": {},
            "children": [
                {
                    "id": "level-1",
                    "style": {},
                    "children": [
                        {
                            "id": "level-2",
                            "style": {},
                            "children": [
                                {"id": "level-3", "style": {}},
                            ],
                        },
                    ],
                },
            ],
        }
        output = {
            "role": "container",
            "description": "Root",
            "children_updates": [
                {"id": "level-1", "role": "container", "description": "L1"},
                {"id": "level-2", "role": "container", "description": "L2"},
                {"id": "level-3", "role": "text", "description": "Deep text"},
            ],
        }
        result = merge_analyzer_output(partial, output)
        deep = result["children"][0]["children"][0]["children"][0]
        assert deep["role"] == "text"
        assert deep["description"] == "Deep text"

    def test_deep_descendants_matched_without_intermediate_update(self):
        """Key fix: deep descendants get updates even when their parent has none.

        Structure: root > card (no update) > header (no update) > title (has update)
        Old code would skip card entirely, never reaching title.
        """
        partial = {
            "id": "root",
            "style": {},
            "children": [
                {
                    "id": "card-1",
                    "name": "Card",
                    "style": {},
                    "children": [
                        {
                            "id": "header-1",
                            "name": "Header",
                            "style": {},
                            "children": [
                                {"id": "title-1", "name": "Title", "style": {}},
                                {"id": "avatar-1", "name": "Avatar", "style": {}},
                            ],
                        },
                    ],
                },
                {"id": "footer-1", "name": "Footer", "style": {}},
            ],
        }
        output = {
            "role": "container",
            "description": "Root",
            "children_updates": [
                # Note: NO update for card-1 or header-1
                {"id": "title-1", "role": "text", "suggested_name": "CardTitle", "description": "标题文字"},
                {"id": "avatar-1", "role": "image", "suggested_name": "UserAvatar", "description": "用户头像"},
                {"id": "footer-1", "role": "footer", "description": "页脚"},
            ],
        }
        result = merge_analyzer_output(partial, output)

        # Deep descendants should be matched
        title = result["children"][0]["children"][0]["children"][0]
        assert title["role"] == "text"
        assert title["name"] == "CardTitle"
        assert title["description"] == "标题文字"

        avatar = result["children"][0]["children"][0]["children"][1]
        assert avatar["role"] == "image"
        assert avatar["name"] == "UserAvatar"

        # Direct child should also work
        footer = result["children"][1]
        assert footer["role"] == "footer"

        # Merge report should show 3/3 matched
        report = result["_merge_report"]
        assert report["children_updates_matched"] == 3
        assert report["children_updates_unmatched"] == []

    def test_unmatched_children_update_ignored(self):
        partial = {
            "id": "root",
            "style": {},
            "children": [
                {"id": "child-1", "style": {}},
            ],
        }
        output = {
            "role": "container",
            "description": "Root",
            "children_updates": [
                {"id": "child-1", "role": "text", "description": "Title"},
                {"id": "nonexistent", "role": "icon", "description": "Ghost"},
            ],
        }
        result = merge_analyzer_output(partial, output)
        assert result["children"][0]["role"] == "text"
        assert len(result["children"]) == 1

    def test_no_children_updates_key(self):
        partial = {
            "id": "root",
            "style": {},
            "children": [{"id": "child-1", "style": {}}],
        }
        output = {"role": "container", "description": "Root"}
        result = merge_analyzer_output(partial, output)
        assert "role" not in result["children"][0]

    def test_children_content_updates(self):
        partial = {
            "id": "root",
            "style": {},
            "children": [
                {
                    "id": "icon-1",
                    "style": {},
                    "content": {"icon": {"name": "unnamed", "size": 24}},
                },
            ],
        }
        output = {
            "role": "header",
            "description": "Nav bar",
            "children_updates": [
                {
                    "id": "icon-1",
                    "role": "icon",
                    "description": "Close button",
                    "content_updates": {"image_alt": None, "icon_name": "close"},
                    "interaction": {
                        "behaviors": [
                            {"trigger": "click", "action": "Navigate back", "target": "page"}
                        ],
                        "states": [],
                    },
                },
            ],
        }
        result = merge_analyzer_output(partial, output)
        child = result["children"][0]
        assert child["role"] == "icon"
        assert child["content"]["icon"]["name"] == "close"
        assert child["interaction"]["behaviors"][0]["trigger"] == "click"


# ── Integration test with real data ──


class TestIntegration:
    def test_topnavbar_merge(self, example_spec, test_cases):
        """Merge TopNavBar partial spec with its expected analyzer output."""
        topnav_partial = example_spec["components"][1]
        assert topnav_partial["name"] == "TopNavBar"

        topnav_case = test_cases["test_cases"][1]
        assert topnav_case["component_name"] == "TopNavBar"

        result = merge_analyzer_output(
            topnav_partial, topnav_case["expected_output"]
        )

        # Top-level fields
        assert result["role"] == "header"
        assert "navigation" in result["description"].lower()

        # StatusBar → spacer
        status_bar = result["children"][0]
        assert status_bar["render_hint"] == "spacer"
        assert status_bar["role"] == "container"

        # NavContent children
        nav_content = result["children"][1]
        assert nav_content["role"] == "container"

        # BackIcon
        back_icon = nav_content["children"][0]
        assert back_icon["role"] == "icon"
        assert back_icon["content"]["icon"]["name"] == "close"
        assert back_icon["interaction"]["behaviors"][0]["trigger"] == "click"

        # TitleGroup
        title_group = nav_content["children"][1]
        assert title_group["role"] == "container"

        # TitleCN
        title_cn = title_group["children"][0]
        assert title_cn["role"] == "text"

        # SubtitleEN
        subtitle = title_group["children"][1]
        assert subtitle["role"] == "text"

        # MoreIcon
        more_icon = nav_content["children"][2]
        assert more_icon["role"] == "icon"
        assert more_icon["content"]["icon"]["name"] == "more-horizontal"

        # Existing structural data preserved
        assert result["bounds"] == {"x": 0, "y": 0, "width": 393, "height": 92}
        assert result["layout"]["type"] == "flex"
        assert result["layout"]["direction"] == "column"

    def test_bottomactionbar_merge(self, example_spec, test_cases):
        """Merge BottomActionBar partial spec with its expected analyzer output."""
        bottom_partial = example_spec["components"][2]
        assert bottom_partial["name"] == "BottomActionBar"

        bottom_case = test_cases["test_cases"][2]
        assert bottom_case["component_name"] == "BottomActionBar"

        result = merge_analyzer_output(
            bottom_partial, bottom_case["expected_output"]
        )

        # Top-level
        assert result["role"] == "footer"

        # GradientStrip
        gradient = result["children"][0]
        assert gradient["role"] == "decorative"

        # CTAButton — interaction merge with existing style_overrides
        cta = result["children"][1]
        assert cta["role"] == "button"
        assert cta["interaction"]["behaviors"][0]["action"] == "Navigate to album live streaming page"

        # CTA hover state: LLM description merged with Node 1 style_overrides
        hover = next(s for s in cta["interaction"]["states"] if s["name"] == "hover")
        assert hover["description"] == "Lighter orange background on hover/press"
        assert hover["style_overrides"]["background"]["color"] == {"value": "#FF8F5E"}

        # CTA active state
        active = next(s for s in cta["interaction"]["states"] if s["name"] == "active")
        assert active["description"] == "Slightly dimmed opacity when pressed"

        # CTA transitions preserved
        assert cta["interaction"]["transitions"][0]["duration_ms"] == 150

        # HomeIndicator
        home = result["children"][2]
        assert home["render_hint"] == "spacer"

    def test_heroimage_merge(self, example_spec, test_cases):
        """Merge HeroImage partial spec with its expected analyzer output."""
        hero_partial = example_spec["components"][0]
        assert hero_partial["name"] == "HeroImage"

        hero_case = test_cases["test_cases"][0]
        assert hero_case["component_name"] == "HeroImage"

        result = merge_analyzer_output(
            hero_partial, hero_case["expected_output"]
        )

        assert result["role"] == "image"
        assert "overflow" in result["description"].lower()
        assert result["content"]["image"]["alt"] == "Album hero artwork — decorative artistic photo for a design event"
        assert result["content"]["image"]["fit"] == "cover"  # preserved


# ── Edge cases ──


class TestEdgeCases:
    def test_empty_partial_spec(self):
        result = merge_analyzer_output({}, {"role": "text", "description": "Test"})
        assert result["role"] == "text"

    def test_empty_analyzer_output(self):
        partial = {"id": "1", "style": {}, "name": "Test"}
        result = merge_analyzer_output(partial, {})
        assert result["name"] == "Test"
        assert "role" not in result

    def test_no_children_no_error(self):
        partial = {"id": "1", "style": {}}
        output = {
            "role": "icon",
            "description": "Icon",
            "children_updates": [
                {"id": "ghost", "role": "text", "description": "Orphan"},
            ],
        }
        result = merge_analyzer_output(partial, output)
        assert result["role"] == "icon"
        assert "children" not in result
