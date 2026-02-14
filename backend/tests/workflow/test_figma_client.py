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
