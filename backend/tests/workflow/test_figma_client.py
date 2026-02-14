"""Tests for workflow.integrations.figma_client."""

import json
import os
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from workflow.integrations.figma_client import FigmaClient, FigmaClientError


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def client():
    """Create a FigmaClient with a test token."""
    return FigmaClient(token="test-figma-token-123")


@pytest.fixture
def sample_nodes_response():
    """Sample Figma /v1/files/:key/nodes response."""
    return {
        "name": "TestFile",
        "nodes": {
            "16650:538": {
                "document": {
                    "id": "16650:538",
                    "name": "白色基础_照片直播",
                    "type": "FRAME",
                    "absoluteBoundingBox": {
                        "x": 80, "y": 318, "width": 393, "height": 852
                    },
                    "children": [
                        {
                            "id": "16650:539",
                            "name": "Header",
                            "type": "FRAME",
                            "visible": True,
                            "absoluteBoundingBox": {
                                "x": 80, "y": 318, "width": 393, "height": 92
                            },
                            "children": [
                                {
                                    "id": "16650:541",
                                    "name": "StatusBar",
                                    "type": "FRAME",
                                    "absoluteBoundingBox": {
                                        "x": 80, "y": 318, "width": 393, "height": 54
                                    },
                                    "children": [],
                                },
                                {
                                    "id": "16650:542",
                                    "name": "AppTitle",
                                    "type": "TEXT",
                                    "characters": "BEAST·野兽派设计会",
                                    "absoluteBoundingBox": {
                                        "x": 160, "y": 376, "width": 233, "height": 22
                                    },
                                    "children": [],
                                },
                            ],
                        },
                        {
                            "id": "16832:22637",
                            "name": "TabBar",
                            "type": "FRAME",
                            "visible": True,
                            "absoluteBoundingBox": {
                                "x": 80, "y": 410, "width": 393, "height": 98
                            },
                            "children": [
                                {
                                    "id": "tab1",
                                    "name": "Tab_图片",
                                    "type": "TEXT",
                                    "characters": "图片",
                                    "absoluteBoundingBox": {"x": 100, "y": 410, "width": 40, "height": 20},
                                    "children": [],
                                },
                                {
                                    "id": "tab2",
                                    "name": "Tab_热门",
                                    "type": "TEXT",
                                    "characters": "热门",
                                    "absoluteBoundingBox": {"x": 160, "y": 410, "width": 40, "height": 20},
                                    "children": [],
                                },
                                {
                                    "id": "filter1",
                                    "name": "Filter_全部照片",
                                    "type": "TEXT",
                                    "characters": "全部照片",
                                    "absoluteBoundingBox": {"x": 100, "y": 450, "width": 60, "height": 20},
                                    "children": [],
                                },
                            ],
                        },
                        {
                            "id": "16650:601",
                            "name": "PhotoGrid",
                            "type": "FRAME",
                            "visible": True,
                            "absoluteBoundingBox": {
                                "x": 88, "y": 508, "width": 377, "height": 716
                            },
                            "children": [
                                {
                                    "id": "16650:605",
                                    "name": "ThumbnailSidebar",
                                    "type": "FRAME",
                                    "absoluteBoundingBox": {"x": 88, "y": 508, "width": 45, "height": 716},
                                    "children": [{"id": f"thumb{i}", "name": f"thumb{i}", "type": "RECTANGLE",
                                                   "absoluteBoundingBox": {"x": 88, "y": 508 + i*50, "width": 40, "height": 40},
                                                   "children": []} for i in range(14)],
                                },
                                {
                                    "id": "16650:602",
                                    "name": "MainPhotoView",
                                    "type": "FRAME",
                                    "absoluteBoundingBox": {"x": 137, "y": 508, "width": 328, "height": 688},
                                    "children": [],
                                },
                            ],
                        },
                        {
                            "id": "invisible_node",
                            "name": "HiddenLayer",
                            "type": "FRAME",
                            "visible": False,
                            "absoluteBoundingBox": {"x": 0, "y": 0, "width": 100, "height": 100},
                            "children": [],
                        },
                    ],
                },
            },
        },
    }


@pytest.fixture
def sample_images_response():
    """Sample Figma /v1/images/:key response."""
    return {
        "images": {
            "16650:539": "https://figma-cdn.example.com/img/header.png",
            "16832:22637": "https://figma-cdn.example.com/img/tabbar.png",
            "16650:601": None,  # Render failed
        }
    }


@pytest.fixture
def sample_variables_response():
    """Sample Figma /v1/files/:key/variables/local response."""
    return {
        "meta": {
            "variables": {
                "var1": {
                    "name": "Brand-主题色/品牌色",
                    "resolvedType": "COLOR",
                    "valuesByMode": {
                        "mode1": {"r": 1.0, "g": 0.867, "b": 0.298, "a": 1.0}
                    },
                },
                "var2": {
                    "name": "Text Color/字体_黑100%",
                    "resolvedType": "COLOR",
                    "valuesByMode": {
                        "mode1": {"r": 0.0, "g": 0.0, "b": 0.0, "a": 1.0}
                    },
                },
                "var3": {
                    "name": "Fill/背景色_页面",
                    "resolvedType": "COLOR",
                    "valuesByMode": {
                        "mode1": {"r": 0.961, "g": 0.961, "b": 0.961, "a": 1.0}
                    },
                },
                "var4": {
                    "name": "spacing/page-padding",
                    "resolvedType": "FLOAT",
                    "valuesByMode": {
                        "mode1": 16,
                    },
                },
            },
            "variableCollections": {},
        }
    }


# ---------------------------------------------------------------------------
# Tests: Constructor & token validation
# ---------------------------------------------------------------------------


class TestFigmaClientInit:

    def test_creates_with_explicit_token(self):
        client = FigmaClient(token="my-token")
        assert client._token == "my-token"

    def test_reads_token_from_env(self, monkeypatch):
        monkeypatch.setenv("FIGMA_TOKEN", "env-token-abc")
        client = FigmaClient()
        assert client._token == "env-token-abc"

    def test_raises_without_token(self, monkeypatch):
        monkeypatch.delenv("FIGMA_TOKEN", raising=False)
        with pytest.raises(FigmaClientError, match="FIGMA_TOKEN"):
            FigmaClient()


# ---------------------------------------------------------------------------
# Tests: API methods (mocked HTTP)
# ---------------------------------------------------------------------------


class TestGetFileNodes:

    @pytest.mark.asyncio
    async def test_returns_nodes(self, client, sample_nodes_response):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = sample_nodes_response

        with patch.object(client, "_get_client") as mock_get_client:
            mock_http = AsyncMock()
            mock_http.get = AsyncMock(return_value=mock_resp)
            mock_get_client.return_value = mock_http

            # Call through _get which uses the client
            result = await client.get_file_nodes("test_key", ["16650:538"])

        assert "nodes" in result
        assert "16650:538" in result["nodes"]

    @pytest.mark.asyncio
    async def test_403_raises_auth_error(self, client):
        mock_resp = MagicMock()
        mock_resp.status_code = 403
        mock_resp.text = "Forbidden"

        with patch.object(client, "_get_client") as mock_get_client:
            mock_http = AsyncMock()
            mock_http.get = AsyncMock(return_value=mock_resp)
            mock_get_client.return_value = mock_http

            with pytest.raises(FigmaClientError, match="403 Forbidden"):
                await client.get_file_nodes("test_key", ["node1"])

    @pytest.mark.asyncio
    async def test_429_raises_rate_limit(self, client):
        mock_resp = MagicMock()
        mock_resp.status_code = 429
        mock_resp.text = "Rate limited"

        with patch.object(client, "_get_client") as mock_get_client:
            mock_http = AsyncMock()
            mock_http.get = AsyncMock(return_value=mock_resp)
            mock_get_client.return_value = mock_http

            with pytest.raises(FigmaClientError, match="rate limit"):
                await client.get_node_images("test_key", ["node1"])


class TestGetNodeImages:

    @pytest.mark.asyncio
    async def test_returns_image_urls(self, client, sample_images_response):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = sample_images_response

        with patch.object(client, "_get_client") as mock_get_client:
            mock_http = AsyncMock()
            mock_http.get = AsyncMock(return_value=mock_resp)
            mock_get_client.return_value = mock_http

            result = await client.get_node_images(
                "test_key", ["16650:539", "16832:22637", "16650:601"]
            )

        assert result["16650:539"] == "https://figma-cdn.example.com/img/header.png"
        assert result["16650:601"] is None  # Failed render

    @pytest.mark.asyncio
    async def test_error_field_raises(self, client):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"err": "Invalid node IDs", "images": {}}

        with patch.object(client, "_get_client") as mock_get_client:
            mock_http = AsyncMock()
            mock_http.get = AsyncMock(return_value=mock_resp)
            mock_get_client.return_value = mock_http

            with pytest.raises(FigmaClientError, match="image render error"):
                await client.get_node_images("test_key", ["bad:id"])


# ---------------------------------------------------------------------------
# Tests: Helper methods
# ---------------------------------------------------------------------------


class TestParseVariables:

    def test_color_rgba_to_hex(self, client, sample_variables_response):
        result = client._parse_variables(sample_variables_response)
        # round(0.298 * 255) = round(75.99) = 76 = 0x4C
        assert result["Brand-主题色/品牌色"] == "#FFDD4C"
        assert result["Text Color/字体_黑100%"] == "#000000"

    def test_bg_color(self, client, sample_variables_response):
        result = client._parse_variables(sample_variables_response)
        assert result["Fill/背景色_页面"] == "#F5F5F5"

    def test_float_value(self, client, sample_variables_response):
        result = client._parse_variables(sample_variables_response)
        assert result["spacing/page-padding"] == "16"


class TestToComponentName:

    @pytest.mark.parametrize("input_name,expected", [
        ("photo-grid", "PhotoGrid"),
        ("Header 区域", "Header"),
        ("bottom_nav", "BottomNav"),
        ("StatusBar", "Statusbar"),
        ("Tab_图片", "Tab"),
        ("simple", "Simple"),
        ("a-b-c", "ABC"),
    ])
    def test_conversion(self, input_name, expected):
        assert FigmaClient._to_component_name(input_name) == expected

    def test_empty_returns_component(self):
        assert FigmaClient._to_component_name("中文名") == "Component"


class TestToCssVarName:

    @pytest.mark.parametrize("input_name,expected", [
        ("Text Color/字体_黑60%", "text-color-60"),
        ("Brand-主题色/品牌色 (100%)", "brand-100"),
        ("Fill/背景色_页面", "fill"),
        ("spacing/page-padding", "spacing-page-padding"),
    ])
    def test_conversion(self, input_name, expected):
        assert FigmaClient._to_css_var_name(input_name) == expected


class TestDetectComponentsFromTree:

    def test_detects_visible_components(self, client, sample_nodes_response):
        page_doc = sample_nodes_response["nodes"]["16650:538"]["document"]
        children = page_doc["children"]
        page_bounds = {"x": 80, "y": 318, "width": 393, "height": 852}

        components, node_ids = client._detect_components_from_tree(
            children, page_bounds
        )

        # Should detect 3 visible components (Header, TabBar, PhotoGrid)
        # The invisible node should be skipped
        assert len(components) == 3
        names = [c["name"] for c in components]
        assert "Header" in names
        assert "Tabbar" in names
        assert "Photogrid" in names

    def test_skips_invisible_nodes(self, client, sample_nodes_response):
        page_doc = sample_nodes_response["nodes"]["16650:538"]["document"]
        children = page_doc["children"]
        page_bounds = {"x": 80, "y": 318, "width": 393, "height": 852}

        components, node_ids = client._detect_components_from_tree(
            children, page_bounds
        )

        node_ids_set = set(node_ids)
        assert "invisible_node" not in node_ids_set

    def test_computes_neighbors(self, client, sample_nodes_response):
        page_doc = sample_nodes_response["nodes"]["16650:538"]["document"]
        children = page_doc["children"]
        page_bounds = {"x": 80, "y": 318, "width": 393, "height": 852}

        components, _ = client._detect_components_from_tree(
            children, page_bounds
        )

        # Sorted by Y position: Header(318) → TabBar(410) → PhotoGrid(508)
        assert components[0]["name"] == "Header"
        assert components[0]["neighbors"] == ["Tabbar"]

        assert components[1]["name"] == "Tabbar"
        assert "Header" in components[1]["neighbors"]
        assert "Photogrid" in components[1]["neighbors"]

        assert components[2]["name"] == "Photogrid"
        assert components[2]["neighbors"] == ["Tabbar"]

    def test_extracts_text_content(self, client, sample_nodes_response):
        page_doc = sample_nodes_response["nodes"]["16650:538"]["document"]
        children = page_doc["children"]
        page_bounds = {"x": 80, "y": 318, "width": 393, "height": 852}

        components, _ = client._detect_components_from_tree(
            children, page_bounds
        )

        # Header contains TEXT node "BEAST·野兽派设计会"
        header = next(c for c in components if c["name"] == "Header")
        assert "BEAST·野兽派设计会" in header["text_content"]

        # TabBar contains text "图片", "热门", "全部照片"
        tabbar = next(c for c in components if c["name"] == "Tabbar")
        assert "图片" in tabbar["text_content"]
        assert "热门" in tabbar["text_content"]

    def test_classifies_large_node_as_section(self, client):
        """A node that covers >25% of page area should be classified as 'section'."""
        children = [{
            "id": "big",
            "name": "BigSection",
            "type": "FRAME",
            "visible": True,
            "absoluteBoundingBox": {"x": 0, "y": 0, "width": 300, "height": 600},
            "children": [],
        }]
        page_bounds = {"width": 400, "height": 800}  # area = 320000

        components, _ = client._detect_components_from_tree(children, page_bounds)
        assert components[0]["type"] == "section"


class TestVariablesToDesignTokens:

    def test_classifies_colors(self, client):
        variables = {
            "Brand-主题色/品牌色": "#FFDD4C",
            "Fill/背景色_页面": "#F5F5F5",
        }
        tokens = client._variables_to_design_tokens(variables)
        assert len(tokens["colors"]) == 2

    def test_classifies_spacing(self, client):
        variables = {
            "spacing/page-padding": "16",
        }
        tokens = client._variables_to_design_tokens(variables)
        assert len(tokens["spacing"]) == 1


# ---------------------------------------------------------------------------
# Tests: generate_design_export (integration, mocked API)
# ---------------------------------------------------------------------------


class TestGenerateDesignExport:

    @pytest.mark.asyncio
    async def test_produces_valid_export_structure(
        self, client, sample_nodes_response, sample_variables_response
    ):
        with tempfile.TemporaryDirectory() as tmpdir:
            # Mock all API calls
            with patch.object(
                client, "get_file_nodes", new_callable=AsyncMock
            ) as mock_nodes, patch.object(
                client, "get_file_variables", new_callable=AsyncMock
            ) as mock_vars, patch.object(
                client, "download_screenshots", new_callable=AsyncMock
            ) as mock_screenshots:

                mock_nodes.return_value = sample_nodes_response
                mock_vars.return_value = sample_variables_response
                mock_screenshots.return_value = {
                    "16650:539": "screenshots/16650_539.png",
                }

                export = await client.generate_design_export(
                    "test_key", "16650:538", output_dir=tmpdir
                )

            # Validate structure
            assert export["version"] == "1.0"
            assert export["source"] == "figma"
            assert export["file_key"] == "test_key"
            assert export["page_node_id"] == "16650:538"
            assert "page_bounds" in export
            assert "variables" in export
            assert "design_tokens" in export
            assert "components" in export
            assert isinstance(export["components"], list)
            assert len(export["components"]) == 3  # Header, TabBar, PhotoGrid

            # Validate design_export.json was written
            export_path = os.path.join(tmpdir, "design_export.json")
            assert os.path.isfile(export_path)
            with open(export_path) as f:
                written = json.load(f)
            assert written["file_key"] == "test_key"

    @pytest.mark.asyncio
    async def test_handles_variable_fetch_failure_gracefully(
        self, client, sample_nodes_response
    ):
        """If variables API fails, should still produce a valid export."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.object(
                client, "get_file_nodes", new_callable=AsyncMock
            ) as mock_nodes, patch.object(
                client, "get_file_variables", new_callable=AsyncMock
            ) as mock_vars, patch.object(
                client, "get_file_styles", new_callable=AsyncMock
            ) as mock_styles, patch.object(
                client, "download_screenshots", new_callable=AsyncMock
            ) as mock_screenshots:

                mock_nodes.return_value = sample_nodes_response
                mock_vars.side_effect = FigmaClientError("Variables API disabled")
                mock_styles.side_effect = FigmaClientError("Styles API error")
                mock_screenshots.return_value = {}

                export = await client.generate_design_export(
                    "test_key", "16650:538", output_dir=tmpdir
                )

            # Should still produce components even without variables
            assert len(export["components"]) == 3
            assert export["variables"] == {}


# ---------------------------------------------------------------------------
# D5: Interaction context extraction
# ---------------------------------------------------------------------------


class TestExtractInteractionContext:
    """Tests for _extract_interaction_context() and related helpers."""

    def test_text_only_frame(self, client):
        """Frame with only TEXT children → text extracted, no visual annotations."""
        node = {
            "id": "100:1",
            "name": "首页-交互说明",
            "type": "FRAME",
            "children": [
                {"type": "TEXT", "characters": "点击Tab切换内容区域"},
                {"type": "TEXT", "characters": "下拉刷新加载更多"},
                {"type": "FRAME", "children": [
                    {"type": "TEXT", "characters": "底部导航固定"},
                ]},
            ],
        }
        ctx = client._extract_interaction_context(node)
        assert ctx["node_id"] == "100:1"
        assert ctx["name"] == "首页-交互说明"
        assert "点击Tab切换内容区域" in ctx["text_content"]
        assert "下拉刷新加载更多" in ctx["text_content"]
        assert "底部导航固定" in ctx["text_content"]
        assert len(ctx["text_content"]) == 3
        assert ctx["has_visual_annotations"] is False
        assert ctx["visual_annotation_types"] == []

    def test_frame_with_arrows(self, client):
        """Frame with ARROW and LINE children → visual annotations detected."""
        node = {
            "id": "200:1",
            "name": "动画效果说明",
            "type": "FRAME",
            "children": [
                {"type": "TEXT", "characters": "启动页logo放大→淡出→首页"},
                {"type": "ARROW", "id": "200:2"},
                {"type": "LINE", "id": "200:3"},
                {"type": "FRAME", "children": [
                    {"type": "VECTOR", "id": "200:4"},
                    {"type": "TEXT", "characters": "duration 800ms"},
                ]},
            ],
        }
        ctx = client._extract_interaction_context(node)
        assert ctx["has_visual_annotations"] is True
        assert "ARROW" in ctx["visual_annotation_types"]
        assert "LINE" in ctx["visual_annotation_types"]
        assert "VECTOR" in ctx["visual_annotation_types"]
        assert len(ctx["text_content"]) == 2
        assert "duration 800ms" in ctx["text_content"]

    def test_empty_frame(self, client):
        """Frame with no children → empty text, no annotations."""
        node = {"id": "300:1", "name": "Empty", "type": "FRAME", "children": []}
        ctx = client._extract_interaction_context(node)
        assert ctx["text_content"] == []
        assert ctx["has_visual_annotations"] is False

    def test_nested_visual_annotations(self, client):
        """Deeply nested VECTOR nodes should still be detected."""
        node = {
            "id": "400:1",
            "name": "流程图",
            "type": "FRAME",
            "children": [
                {"type": "GROUP", "children": [
                    {"type": "GROUP", "children": [
                        {"type": "BOOLEAN_OPERATION", "id": "400:5"},
                    ]},
                ]},
            ],
        }
        ctx = client._extract_interaction_context(node)
        assert ctx["has_visual_annotations"] is True
        assert "BOOLEAN_OPERATION" in ctx["visual_annotation_types"]

    def test_frame_with_star_polygon(self, client):
        """STAR and POLYGON are also visual annotation indicators."""
        node = {
            "id": "500:1",
            "name": "标注说明",
            "type": "FRAME",
            "children": [
                {"type": "STAR", "id": "500:2"},
                {"type": "POLYGON", "id": "500:3"},
                {"type": "TEXT", "characters": "重点标注"},
            ],
        }
        ctx = client._extract_interaction_context(node)
        assert ctx["has_visual_annotations"] is True
        assert "STAR" in ctx["visual_annotation_types"]
        assert "POLYGON" in ctx["visual_annotation_types"]
        assert ctx["text_content"] == ["重点标注"]


class TestDetectVisualAnnotations:
    """Tests for _detect_visual_annotations() helper."""

    def test_no_annotations(self, client):
        """Frame with only FRAME/TEXT/GROUP children → empty set."""
        node = {
            "type": "FRAME",
            "children": [
                {"type": "TEXT", "characters": "hello"},
                {"type": "GROUP", "children": [
                    {"type": "FRAME", "children": []},
                ]},
            ],
        }
        result = client._detect_visual_annotations(node)
        assert result == set()

    def test_mixed_annotations(self, client):
        """Detects all annotation types in a mixed tree."""
        node = {
            "type": "FRAME",
            "children": [
                {"type": "LINE", "children": []},
                {"type": "ARROW", "children": []},
                {"type": "TEXT", "characters": "label"},
                {"type": "FRAME", "children": [
                    {"type": "VECTOR", "children": []},
                ]},
            ],
        }
        result = client._detect_visual_annotations(node)
        assert result == {"LINE", "ARROW", "VECTOR"}

    def test_root_is_annotation_type(self, client):
        """Root node itself is an annotation type."""
        node = {"type": "VECTOR", "children": []}
        result = client._detect_visual_annotations(node)
        assert result == {"VECTOR"}


class TestExtractInteractionContextsBatch:
    """Tests for extract_interaction_contexts() async batch method."""

    @pytest.mark.asyncio
    async def test_batch_no_visual_annotations(self, client):
        """Batch extraction with text-only frames → no screenshots requested."""
        nodes = [
            {"id": "10:1", "name": "交互说明A", "type": "FRAME", "children": [
                {"type": "TEXT", "characters": "点击跳转"},
            ]},
            {"id": "10:2", "name": "交互说明B", "type": "FRAME", "children": [
                {"type": "TEXT", "characters": "下滑加载"},
            ]},
        ]
        results = await client.extract_interaction_contexts("fk", nodes)
        assert len(results) == 2
        assert results[0]["text_content"] == ["点击跳转"]
        assert results[1]["text_content"] == ["下滑加载"]
        assert all(not r["has_visual_annotations"] for r in results)
        assert all("screenshot_path" not in r for r in results)

    @pytest.mark.asyncio
    async def test_batch_with_visual_annotations_downloads_screenshots(self, client):
        """Frames with visual annotations → screenshots downloaded."""
        nodes = [
            {"id": "20:1", "name": "纯文本", "type": "FRAME", "children": [
                {"type": "TEXT", "characters": "说明文字"},
            ]},
            {"id": "20:2", "name": "带箭头", "type": "FRAME", "children": [
                {"type": "ARROW", "id": "20:3"},
                {"type": "TEXT", "characters": "流程说明"},
            ]},
        ]

        with patch.object(
            client, "get_node_images", new_callable=AsyncMock
        ) as mock_images:
            mock_images.return_value = {
                "20:2": "https://figma-cdn.example.com/arrow_frame.png",
            }

            # Mock the download
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.content = b"PNG_DATA"

            with patch("httpx.AsyncClient") as mock_http_cls:
                mock_http_inst = AsyncMock()
                mock_http_inst.get.return_value = mock_resp
                mock_http_inst.__aenter__ = AsyncMock(return_value=mock_http_inst)
                mock_http_inst.__aexit__ = AsyncMock(return_value=None)
                mock_http_cls.return_value = mock_http_inst

                import tempfile
                with tempfile.TemporaryDirectory() as tmpdir:
                    results = await client.extract_interaction_contexts(
                        "fk", nodes, output_dir=tmpdir
                    )

            assert len(results) == 2
            # First frame: text only, no screenshot
            assert not results[0]["has_visual_annotations"]
            assert "screenshot_path" not in results[0]
            # Second frame: has arrows, screenshot downloaded
            assert results[1]["has_visual_annotations"]
            assert results[1]["screenshot_path"] == "interaction_screenshots/20_2.png"
            # get_node_images called with only the visual annotation frame
            mock_images.assert_called_once_with("fk", ["20:2"], fmt="png", scale=1)

    @pytest.mark.asyncio
    async def test_batch_image_fetch_failure_graceful(self, client):
        """If image fetch fails, should still return text content."""
        nodes = [
            {"id": "30:1", "name": "有箭头", "type": "FRAME", "children": [
                {"type": "LINE", "id": "30:2"},
                {"type": "TEXT", "characters": "重要说明"},
            ]},
        ]

        with patch.object(
            client, "get_node_images", new_callable=AsyncMock
        ) as mock_images:
            mock_images.side_effect = FigmaClientError("API error")

            results = await client.extract_interaction_contexts("fk", nodes)

        assert len(results) == 1
        assert results[0]["text_content"] == ["重要说明"]
        assert results[0]["has_visual_annotations"] is True
        assert "screenshot_path" not in results[0]


# ---------------------------------------------------------------------------
# D1: scan_and_classify_frames — rule-based classification
# ---------------------------------------------------------------------------


class TestClassifyFrameByRules:
    """Tests for _classify_frame_by_rules()."""

    def test_mobile_screen(self, client):
        """393×852 frame → ui_screen, mobile."""
        node = {
            "id": "1:1", "name": "通屏效果", "type": "FRAME", "visible": True,
            "absoluteBoundingBox": {"x": 0, "y": 0, "width": 393, "height": 852},
        }
        result = client._classify_frame_by_rules(node)
        assert result["classification"] == "ui_screen"
        assert result["device_type"] == "mobile"
        assert result["confidence"] >= 0.9

    def test_mobile_375(self, client):
        """375×812 (iPhone) → ui_screen, mobile."""
        node = {
            "id": "1:2", "name": "首页", "type": "FRAME", "visible": True,
            "absoluteBoundingBox": {"x": 500, "y": 0, "width": 375, "height": 812},
        }
        result = client._classify_frame_by_rules(node)
        assert result["classification"] == "ui_screen"
        assert result["device_type"] == "mobile"

    def test_mobile_tolerance(self, client):
        """Width within ±10px of known size → still matches."""
        node = {
            "id": "1:3", "name": "测试页", "type": "FRAME", "visible": True,
            "absoluteBoundingBox": {"x": 0, "y": 0, "width": 398, "height": 700},
        }
        result = client._classify_frame_by_rules(node)
        assert result["classification"] == "ui_screen"
        assert result["device_type"] == "mobile"

    def test_tablet_screen(self, client):
        """768×1024 → ui_screen, tablet."""
        node = {
            "id": "2:1", "name": "iPad 首页", "type": "FRAME", "visible": True,
            "absoluteBoundingBox": {"x": 0, "y": 0, "width": 768, "height": 1024},
        }
        result = client._classify_frame_by_rules(node)
        assert result["classification"] == "ui_screen"
        assert result["device_type"] == "tablet"

    def test_desktop_screen(self, client):
        """1440×900 → ui_screen, desktop."""
        node = {
            "id": "3:1", "name": "Dashboard", "type": "FRAME", "visible": True,
            "absoluteBoundingBox": {"x": 0, "y": 0, "width": 1440, "height": 900},
        }
        result = client._classify_frame_by_rules(node)
        assert result["classification"] == "ui_screen"
        assert result["device_type"] == "desktop"

    def test_wide_banner_excluded(self, client):
        """Very wide aspect ratio → excluded."""
        node = {
            "id": "3:2", "name": "Banner", "type": "FRAME", "visible": True,
            "absoluteBoundingBox": {"x": 0, "y": 0, "width": 1920, "height": 200},
        }
        result = client._classify_frame_by_rules(node)
        assert result["classification"] == "excluded"
        assert "wide_banner" in result["reason"]

    def test_exclude_keyword(self, client):
        """Frame name containing exclude keyword → excluded."""
        node = {
            "id": "4:1", "name": "参考图片", "type": "FRAME", "visible": True,
            "absoluteBoundingBox": {"x": 0, "y": 0, "width": 393, "height": 852},
        }
        result = client._classify_frame_by_rules(node)
        assert result["classification"] == "excluded"
        assert "keyword_match" in result["reason"]

    def test_interaction_keyword(self, client):
        """Frame name with interaction keyword → interaction_spec."""
        node = {
            "id": "5:1", "name": "首页交互说明", "type": "FRAME", "visible": True,
            "absoluteBoundingBox": {"x": 500, "y": 0, "width": 600, "height": 400},
        }
        result = client._classify_frame_by_rules(node)
        assert result["classification"] == "interaction_spec"

    def test_design_system_keyword(self, client):
        """Frame name with design system keyword → design_system."""
        node = {
            "id": "6:1", "name": "颜色系统", "type": "FRAME", "visible": True,
            "absoluteBoundingBox": {"x": 0, "y": 0, "width": 700, "height": 400},
        }
        result = client._classify_frame_by_rules(node)
        assert result["classification"] == "design_system"

    def test_invisible_excluded(self, client):
        """Invisible frame → excluded."""
        node = {
            "id": "7:1", "name": "Hidden", "type": "FRAME", "visible": False,
            "absoluteBoundingBox": {"x": 0, "y": 0, "width": 393, "height": 852},
        }
        result = client._classify_frame_by_rules(node)
        assert result["classification"] == "excluded"
        assert result["reason"] == "invisible"

    def test_zero_size_excluded(self, client):
        """Zero-size frame → excluded."""
        node = {
            "id": "8:1", "name": "Empty", "type": "FRAME", "visible": True,
            "absoluteBoundingBox": {"x": 0, "y": 0, "width": 0, "height": 0},
        }
        result = client._classify_frame_by_rules(node)
        assert result["classification"] == "excluded"
        assert result["reason"] == "zero_size"

    def test_unknown_size(self, client):
        """Unrecognized size, no keyword → unknown."""
        node = {
            "id": "9:1", "name": "神秘内容", "type": "FRAME", "visible": True,
            "absoluteBoundingBox": {"x": 0, "y": 0, "width": 500, "height": 300},
        }
        result = client._classify_frame_by_rules(node)
        assert result["classification"] == "unknown"
        assert result["confidence"] == 0.0

    def test_exclude_keyword_priority_over_size(self, client):
        """Exclude keyword takes priority even if size matches mobile."""
        node = {
            "id": "10:1", "name": "旧版首页", "type": "FRAME", "visible": True,
            "absoluteBoundingBox": {"x": 0, "y": 0, "width": 393, "height": 852},
        }
        result = client._classify_frame_by_rules(node)
        assert result["classification"] == "excluded"


class TestAssociateSpecsToScreens:
    """Tests for _associate_specs_to_screens()."""

    def test_nearest_screen(self, client):
        """Spec is associated with its nearest screen."""
        screens = [
            {"node_id": "s1", "name": "首页", "bounds": {"x": 0, "y": 0, "width": 393, "height": 852}},
            {"node_id": "s2", "name": "详情页", "bounds": {"x": 500, "y": 0, "width": 393, "height": 852}},
        ]
        specs = [
            {"node_id": "sp1", "name": "交互A", "bounds": {"x": 450, "y": 100, "width": 200, "height": 300}},
        ]
        client._associate_specs_to_screens(screens, specs)
        # sp1 is closer to s2 (x=500) than s1 (x=0)
        assert specs[0]["related_to"]["node_id"] == "s2"

    def test_name_prefix_bonus(self, client):
        """Name prefix match gives strong association bonus."""
        screens = [
            {"node_id": "s1", "name": "首页", "bounds": {"x": 0, "y": 0, "width": 393, "height": 852}},
            {"node_id": "s2", "name": "详情页", "bounds": {"x": 500, "y": 0, "width": 393, "height": 852}},
        ]
        specs = [
            # Spec is closer to s2 by position, but name matches s1
            {"node_id": "sp1", "name": "首页-交互说明", "bounds": {"x": 450, "y": 100, "width": 200, "height": 300}},
        ]
        client._associate_specs_to_screens(screens, specs)
        # Name bonus overrides proximity
        assert specs[0]["related_to"]["node_id"] == "s1"

    def test_empty_specs(self, client):
        """No specs → no-op."""
        screens = [{"node_id": "s1", "name": "A", "bounds": {"x": 0, "y": 0, "width": 100, "height": 100}}]
        specs = []
        client._associate_specs_to_screens(screens, specs)
        # No crash

    def test_empty_screens(self, client):
        """No screens → specs get no related_to."""
        screens = []
        specs = [{"node_id": "sp1", "name": "A", "bounds": {"x": 0, "y": 0, "width": 100, "height": 100}}]
        client._associate_specs_to_screens(screens, specs)
        assert "related_to" not in specs[0]


class TestScanAndClassifyFrames:
    """Tests for scan_and_classify_frames() async method."""

    @pytest.mark.asyncio
    async def test_basic_classification(self, client):
        """Classifies a mix of UI screens, specs, and excluded frames."""
        page_response = {
            "nodes": {
                "page:1": {
                    "document": {
                        "id": "page:1",
                        "name": "测试页面",
                        "type": "PAGE",
                        "children": [
                            {
                                "id": "f:1", "name": "通屏效果", "type": "FRAME",
                                "visible": True,
                                "absoluteBoundingBox": {"x": 0, "y": 0, "width": 393, "height": 852},
                                "children": [],
                            },
                            {
                                "id": "f:2", "name": "首页交互说明", "type": "FRAME",
                                "visible": True,
                                "absoluteBoundingBox": {"x": 450, "y": 0, "width": 600, "height": 400},
                                "children": [
                                    {"type": "TEXT", "characters": "点击跳转"},
                                ],
                            },
                            {
                                "id": "f:3", "name": "参考图", "type": "FRAME",
                                "visible": True,
                                "absoluteBoundingBox": {"x": 1200, "y": 0, "width": 800, "height": 600},
                                "children": [],
                            },
                        ],
                    },
                },
            },
        }

        with patch.object(client, "get_file_nodes", new_callable=AsyncMock) as mock_nodes:
            mock_nodes.return_value = page_response
            result = await client.scan_and_classify_frames("fk", "page:1")

        assert result["page_name"] == "测试页面"
        assert len(result["candidates"]) == 1
        assert result["candidates"][0]["name"] == "通屏效果"
        assert len(result["interaction_specs"]) == 1
        assert result["interaction_specs"][0]["name"] == "首页交互说明"
        assert result["interaction_specs"][0]["text_content"] == ["点击跳转"]
        assert len(result["excluded"]) == 1

    @pytest.mark.asyncio
    async def test_section_recursion(self, client):
        """Frames inside SECTION nodes are scanned recursively."""
        page_response = {
            "nodes": {
                "page:1": {
                    "document": {
                        "id": "page:1",
                        "name": "页面",
                        "type": "PAGE",
                        "children": [
                            {
                                "id": "sec:1", "name": "效果图", "type": "SECTION",
                                "visible": True,
                                "absoluteBoundingBox": {"x": 0, "y": 0, "width": 2000, "height": 1000},
                                "children": [
                                    {
                                        "id": "f:1", "name": "首页", "type": "FRAME",
                                        "visible": True,
                                        "absoluteBoundingBox": {"x": 0, "y": 0, "width": 393, "height": 852},
                                        "children": [],
                                    },
                                    {
                                        "id": "f:2", "name": "详情页", "type": "FRAME",
                                        "visible": True,
                                        "absoluteBoundingBox": {"x": 500, "y": 0, "width": 393, "height": 852},
                                        "children": [],
                                    },
                                ],
                            },
                        ],
                    },
                },
            },
        }

        with patch.object(client, "get_file_nodes", new_callable=AsyncMock) as mock_nodes:
            mock_nodes.return_value = page_response
            result = await client.scan_and_classify_frames("fk", "page:1")

        assert len(result["candidates"]) == 2
        assert result["candidates"][0]["section"] == "效果图"
        assert result["candidates"][1]["section"] == "效果图"

    @pytest.mark.asyncio
    async def test_spec_association(self, client):
        """Interaction specs are associated with nearest UI screen."""
        page_response = {
            "nodes": {
                "page:1": {
                    "document": {
                        "id": "page:1",
                        "name": "页面",
                        "type": "PAGE",
                        "children": [
                            {
                                "id": "f:1", "name": "首页", "type": "FRAME",
                                "visible": True,
                                "absoluteBoundingBox": {"x": 0, "y": 0, "width": 393, "height": 852},
                                "children": [],
                            },
                            {
                                "id": "f:2", "name": "首页交互说明", "type": "FRAME",
                                "visible": True,
                                "absoluteBoundingBox": {"x": 450, "y": 0, "width": 600, "height": 400},
                                "children": [
                                    {"type": "TEXT", "characters": "Tab切换"},
                                ],
                            },
                        ],
                    },
                },
            },
        }

        with patch.object(client, "get_file_nodes", new_callable=AsyncMock) as mock_nodes:
            mock_nodes.return_value = page_response
            result = await client.scan_and_classify_frames("fk", "page:1")

        assert len(result["interaction_specs"]) == 1
        spec = result["interaction_specs"][0]
        assert "related_to" in spec
        assert spec["related_to"]["node_id"] == "f:1"
        assert spec["related_to"]["name"] == "首页"

    @pytest.mark.asyncio
    async def test_llm_classifier_integration(self, client):
        """LLM classifier is called for unknown frames."""
        page_response = {
            "nodes": {
                "page:1": {
                    "document": {
                        "id": "page:1",
                        "name": "页面",
                        "type": "PAGE",
                        "children": [
                            {
                                "id": "f:1", "name": "神秘内容", "type": "FRAME",
                                "visible": True,
                                "absoluteBoundingBox": {"x": 0, "y": 0, "width": 500, "height": 300},
                                "children": [],
                            },
                        ],
                    },
                },
            },
        }

        async def mock_llm_classifier(summary):
            return [{"node_id": "f:1", "classification": "interaction_spec", "confidence": 0.8, "reason": "looks like spec"}]

        with patch.object(client, "get_file_nodes", new_callable=AsyncMock) as mock_nodes:
            mock_nodes.return_value = page_response
            result = await client.scan_and_classify_frames("fk", "page:1", llm_classifier=mock_llm_classifier)

        assert len(result["interaction_specs"]) == 1
        assert result["interaction_specs"][0]["reason"] == "llm:looks like spec"
        assert len(result["unknown"]) == 0

    @pytest.mark.asyncio
    async def test_llm_classifier_failure_fallback(self, client):
        """If LLM classifier fails, unknown frames stay as unknown."""
        page_response = {
            "nodes": {
                "page:1": {
                    "document": {
                        "id": "page:1",
                        "name": "页面",
                        "type": "PAGE",
                        "children": [
                            {
                                "id": "f:1", "name": "神秘内容", "type": "FRAME",
                                "visible": True,
                                "absoluteBoundingBox": {"x": 0, "y": 0, "width": 500, "height": 300},
                                "children": [],
                            },
                        ],
                    },
                },
            },
        }

        async def failing_classifier(summary):
            raise RuntimeError("LLM API down")

        with patch.object(client, "get_file_nodes", new_callable=AsyncMock) as mock_nodes:
            mock_nodes.return_value = page_response
            result = await client.scan_and_classify_frames("fk", "page:1", llm_classifier=failing_classifier)

        assert len(result["unknown"]) == 1
        assert result["unknown"][0]["name"] == "神秘内容"

    @pytest.mark.asyncio
    async def test_small_node_warning(self, client):
        """Scanning a small component node produces a warning."""
        page_response = {
            "nodes": {
                "comp:1": {
                    "document": {
                        "id": "comp:1",
                        "name": "Status Bar - iPhone",
                        "type": "FRAME",
                        "absoluteBoundingBox": {"x": 0, "y": 0, "width": 138, "height": 54},
                        "children": [
                            {
                                "id": "c:1", "name": "Time", "type": "TEXT",
                                "visible": True, "characters": "9:41",
                                "absoluteBoundingBox": {"x": 0, "y": 0, "width": 138, "height": 54},
                                "children": [],
                            },
                        ],
                    },
                },
            },
        }

        with patch.object(client, "get_file_nodes", new_callable=AsyncMock) as mock_nodes:
            mock_nodes.return_value = page_response
            result = await client.scan_and_classify_frames("fk", "comp:1")

        assert len(result["candidates"]) == 0
        assert len(result["warnings"]) == 1
        assert "138×54" in result["warnings"][0]
        assert "完整的 UI 页面" in result["warnings"][0]

    @pytest.mark.asyncio
    async def test_page_node_no_warning(self, client):
        """Scanning a PAGE node does not produce a small-node warning."""
        page_response = {
            "nodes": {
                "page:1": {
                    "document": {
                        "id": "page:1",
                        "name": "设计稿",
                        "type": "PAGE",
                        "children": [],
                    },
                },
            },
        }

        with patch.object(client, "get_file_nodes", new_callable=AsyncMock) as mock_nodes:
            mock_nodes.return_value = page_response
            result = await client.scan_and_classify_frames("fk", "page:1")

        assert result["warnings"] == []


class TestResolveToPage:
    """Tests for resolve_to_page() auto-parent-page resolution."""

    @pytest.mark.asyncio
    async def test_page_node_returns_none(self, client):
        """PAGE type node → no resolution needed."""
        doc = {"type": "PAGE", "absoluteBoundingBox": {}}
        result = await client.resolve_to_page("fk", "page:1", doc)
        assert result is None

    @pytest.mark.asyncio
    async def test_large_frame_returns_none(self, client):
        """Frame large enough → no resolution needed."""
        doc = {
            "type": "FRAME",
            "absoluteBoundingBox": {"x": 0, "y": 0, "width": 393, "height": 852},
        }
        result = await client.resolve_to_page("fk", "f:1", doc)
        assert result is None

    @pytest.mark.asyncio
    async def test_small_node_resolves_to_containing_page(self, client):
        """Small node spatially inside a frame → resolves to that page."""
        # Target: Status Bar at (100, 318), 138×54 — inside a 393×852 frame at (80, 318)
        doc = {
            "type": "FRAME",
            "absoluteBoundingBox": {"x": 100, "y": 318, "width": 138, "height": 54},
        }
        file_structure = {
            "document": {
                "children": [
                    {
                        "id": "0:1",
                        "name": "Page 1",
                        "type": "CANVAS",
                        "children": [
                            {
                                "id": "f:1",
                                "type": "FRAME",
                                "absoluteBoundingBox": {"x": 80, "y": 318, "width": 393, "height": 852},
                            },
                            {
                                "id": "f:2",
                                "type": "FRAME",
                                "absoluteBoundingBox": {"x": 600, "y": 318, "width": 393, "height": 852},
                            },
                        ],
                    },
                ],
            },
        }

        with patch.object(client, "_get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = file_structure
            result = await client.resolve_to_page("fk", "5574:3322", doc)

        assert result is not None
        assert result["page_id"] == "0:1"
        assert result["page_name"] == "Page 1"

    @pytest.mark.asyncio
    async def test_single_page_fallback(self, client):
        """Small node not spatially matched but single-page file → use that page."""
        doc = {
            "type": "FRAME",
            "absoluteBoundingBox": {"x": 9999, "y": 9999, "width": 50, "height": 50},
        }
        file_structure = {
            "document": {
                "children": [
                    {
                        "id": "0:1",
                        "name": "唯一页面",
                        "type": "CANVAS",
                        "children": [
                            {
                                "id": "f:1",
                                "type": "FRAME",
                                "absoluteBoundingBox": {"x": 0, "y": 0, "width": 393, "height": 852},
                            },
                        ],
                    },
                ],
            },
        }

        with patch.object(client, "_get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = file_structure
            result = await client.resolve_to_page("fk", "c:1", doc)

        assert result is not None
        assert result["page_id"] == "0:1"

    @pytest.mark.asyncio
    async def test_multi_page_no_match_returns_none(self, client):
        """Small node not inside any frame in multi-page file → None."""
        doc = {
            "type": "FRAME",
            "absoluteBoundingBox": {"x": 9999, "y": 9999, "width": 50, "height": 50},
        }
        file_structure = {
            "document": {
                "children": [
                    {"id": "0:1", "name": "Page A", "type": "CANVAS", "children": [
                        {"id": "f:1", "type": "FRAME",
                         "absoluteBoundingBox": {"x": 0, "y": 0, "width": 393, "height": 852}},
                    ]},
                    {"id": "0:2", "name": "Page B", "type": "CANVAS", "children": [
                        {"id": "f:2", "type": "FRAME",
                         "absoluteBoundingBox": {"x": 500, "y": 0, "width": 393, "height": 852}},
                    ]},
                ],
            },
        }

        with patch.object(client, "_get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = file_structure
            result = await client.resolve_to_page("fk", "c:1", doc)

        assert result is None

    @pytest.mark.asyncio
    async def test_api_failure_returns_none(self, client):
        """Figma API failure → graceful None return."""
        from workflow.integrations.figma_client import FigmaClientError

        doc = {
            "type": "FRAME",
            "absoluteBoundingBox": {"x": 0, "y": 0, "width": 50, "height": 50},
        }

        with patch.object(client, "_get", new_callable=AsyncMock) as mock_get:
            mock_get.side_effect = FigmaClientError("API error")
            result = await client.resolve_to_page("fk", "c:1", doc)

        assert result is None
