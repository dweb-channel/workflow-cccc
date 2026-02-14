"""Figma REST API client for the Design-to-Code pipeline.

Fetches node trees, rendered screenshots, and design styles from Figma files
using Personal Access Token (PAT) authentication.

Environment:
    FIGMA_TOKEN — Figma Personal Access Token (required)

Usage:
    client = FigmaClient()
    nodes = await client.get_file_nodes("6kGd851qaAX4TiL44vpIrO", ["16650:538"])
    images = await client.get_node_images("6kGd851qaAX4TiL44vpIrO", ["16650:539"])
    export = await client.generate_design_export("6kGd851qaAX4TiL44vpIrO", "16650:538")
"""

import json
import logging
import os
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import httpx

logger = logging.getLogger("workflow.integrations.figma")

FIGMA_API_BASE = "https://api.figma.com"


class FigmaClientError(Exception):
    """Raised when a Figma API call fails."""


class FigmaClient:
    """Async Figma REST API client.

    Args:
        token: Figma PAT. Falls back to FIGMA_TOKEN env var.
        timeout: HTTP request timeout in seconds.
    """

    def __init__(
        self,
        token: Optional[str] = None,
        timeout: float = 30.0,
    ):
        self._token = token or os.getenv("FIGMA_TOKEN", "")
        if not self._token:
            raise FigmaClientError(
                "Figma token not configured. Set FIGMA_TOKEN environment variable "
                "or pass token= to FigmaClient()."
            )
        self._client: Optional[httpx.AsyncClient] = None
        self._timeout = timeout

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=FIGMA_API_BASE,
                headers={"X-FIGMA-TOKEN": self._token},
                timeout=self._timeout,
                limits=httpx.Limits(max_connections=5, max_keepalive_connections=3),
            )
        return self._client

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def _get(self, path: str, params: Optional[Dict] = None) -> Dict[str, Any]:
        """Make a GET request to the Figma API."""
        client = await self._get_client()
        try:
            resp = await client.get(path, params=params)
        except httpx.TimeoutException as e:
            raise FigmaClientError(f"Figma API timeout: {path}") from e
        except httpx.ConnectError as e:
            raise FigmaClientError(f"Figma API connection error: {path}") from e

        if resp.status_code == 403:
            raise FigmaClientError(
                "Figma API returned 403 Forbidden. Check that FIGMA_TOKEN is valid "
                "and has file_content:read scope."
            )
        if resp.status_code == 404:
            raise FigmaClientError(f"Figma resource not found: {path}")
        if resp.status_code == 429:
            raise FigmaClientError("Figma API rate limit exceeded. Retry later.")
        if resp.status_code != 200:
            raise FigmaClientError(
                f"Figma API error {resp.status_code}: {resp.text[:200]}"
            )

        return resp.json()

    # ------------------------------------------------------------------
    # Core API methods
    # ------------------------------------------------------------------

    async def get_file_nodes(
        self,
        file_key: str,
        node_ids: List[str],
    ) -> Dict[str, Any]:
        """Fetch specific nodes from a Figma file.

        GET /v1/files/:key/nodes?ids=...

        Args:
            file_key: Figma file key (from URL).
            node_ids: List of node IDs (e.g. ["16650:538", "16650:539"]).

        Returns:
            Raw Figma API response with 'nodes' dict mapping node_id → node data.
        """
        ids_param = ",".join(node_ids)
        data = await self._get(f"/v1/files/{file_key}/nodes", params={"ids": ids_param})
        logger.info(
            f"get_file_nodes: file={file_key}, requested={len(node_ids)}, "
            f"returned={len(data.get('nodes', {}))}"
        )
        return data

    async def get_node_images(
        self,
        file_key: str,
        node_ids: List[str],
        fmt: str = "png",
        scale: int = 2,
    ) -> Dict[str, Optional[str]]:
        """Render node screenshots via Figma's image export API.

        GET /v1/images/:key?ids=...&format=png&scale=2

        Args:
            file_key: Figma file key.
            node_ids: List of node IDs to render.
            fmt: Image format ('png', 'svg', 'jpg', 'pdf').
            scale: Render scale (1-4). Default 2 for retina.

        Returns:
            Dict mapping node_id → image URL (or None if render failed).
            URLs expire after 30 days.
        """
        ids_param = ",".join(node_ids)
        data = await self._get(
            f"/v1/images/{file_key}",
            params={"ids": ids_param, "format": fmt, "scale": str(scale)},
        )

        if data.get("err"):
            raise FigmaClientError(f"Figma image render error: {data['err']}")

        images = data.get("images", {})
        logger.info(
            f"get_node_images: file={file_key}, requested={len(node_ids)}, "
            f"rendered={sum(1 for v in images.values() if v)}"
        )
        return images

    async def get_file_styles(
        self,
        file_key: str,
    ) -> Dict[str, Any]:
        """Fetch published styles from a Figma file.

        GET /v1/files/:key/styles

        Args:
            file_key: Figma file key.

        Returns:
            Raw Figma API response with 'meta.styles' list.
        """
        data = await self._get(f"/v1/files/{file_key}/styles")
        styles = data.get("meta", {}).get("styles", [])
        logger.info(f"get_file_styles: file={file_key}, styles_count={len(styles)}")
        return data

    async def get_file_variables(
        self,
        file_key: str,
    ) -> Dict[str, Any]:
        """Fetch local variables from a Figma file.

        GET /v1/files/:key/variables/local

        Args:
            file_key: Figma file key.

        Returns:
            Raw Figma API response with variable collections and variables.
        """
        data = await self._get(f"/v1/files/{file_key}/variables/local")
        logger.info(f"get_file_variables: file={file_key}")
        return data

    # ------------------------------------------------------------------
    # Screenshot download
    # ------------------------------------------------------------------

    async def download_screenshots(
        self,
        file_key: str,
        node_ids: List[str],
        output_dir: str,
        fmt: str = "png",
        scale: int = 2,
    ) -> Dict[str, str]:
        """Download node screenshots to disk.

        1. Calls get_node_images() to get render URLs
        2. Downloads each image to {output_dir}/screenshots/{node_id}.{fmt}

        Args:
            file_key: Figma file key.
            node_ids: Node IDs to render and download.
            output_dir: Base output directory.
            fmt: Image format.
            scale: Render scale.

        Returns:
            Dict mapping node_id → relative file path (from output_dir).
        """
        screenshots_dir = os.path.join(output_dir, "screenshots")
        os.makedirs(screenshots_dir, exist_ok=True)

        # Get render URLs
        image_urls = await self.get_node_images(file_key, node_ids, fmt=fmt, scale=scale)

        client = await self._get_client()
        downloaded: Dict[str, str] = {}

        for node_id, url in image_urls.items():
            if not url:
                logger.warning(f"download_screenshots: No image URL for node {node_id}")
                continue

            # Sanitize node_id for filename: "16650:539" → "16650_539"
            safe_id = node_id.replace(":", "_")
            filename = f"{safe_id}.{fmt}"
            filepath = os.path.join(screenshots_dir, filename)
            rel_path = f"screenshots/{filename}"

            try:
                # Download the image (URL is on Figma CDN, not api.figma.com)
                async with httpx.AsyncClient(timeout=30.0) as dl_client:
                    img_resp = await dl_client.get(url)
                if img_resp.status_code == 200:
                    with open(filepath, "wb") as f:
                        f.write(img_resp.content)
                    downloaded[node_id] = rel_path
                    logger.info(
                        f"download_screenshots: {node_id} → {rel_path} "
                        f"({len(img_resp.content)} bytes)"
                    )
                else:
                    logger.warning(
                        f"download_screenshots: Failed to download {node_id}: "
                        f"HTTP {img_resp.status_code}"
                    )
            except Exception as e:
                logger.warning(f"download_screenshots: Error downloading {node_id}: {e}")

        logger.info(
            f"download_screenshots: {len(downloaded)}/{len(node_ids)} screenshots saved"
        )
        return downloaded

    # ------------------------------------------------------------------
    # High-level: generate design_export.json
    # ------------------------------------------------------------------

    async def generate_design_export(
        self,
        file_key: str,
        page_node_id: str,
        output_dir: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Generate a design_export.json-compatible structure from Figma API.

        Combines get_file_nodes, get_node_images, and get_file_variables
        to produce the same format consumed by DesignAnalyzerNode.

        Args:
            file_key: Figma file key.
            page_node_id: Root node ID of the page/frame to analyze.
            output_dir: If provided, downloads screenshots to disk and
                        sets screenshot_path fields in the output.

        Returns:
            Dict in design_export.json format.
        """
        # 1. Fetch the page node tree
        nodes_resp = await self.get_file_nodes(file_key, [page_node_id])
        nodes_data = nodes_resp.get("nodes", {})

        page_data = nodes_data.get(page_node_id, {})
        page_doc = page_data.get("document", {})

        # Extract file metadata
        file_name = nodes_resp.get("name", "")

        # Extract page bounds from the root node
        bbox = page_doc.get("absoluteBoundingBox", {})
        page_bounds = {
            "x": bbox.get("x", 0),
            "y": bbox.get("y", 0),
            "width": bbox.get("width", 0),
            "height": bbox.get("height", 0),
        }

        # 2. Extract variables from file
        variables_map = {}
        try:
            vars_resp = await self.get_file_variables(file_key)
            variables_map = self._parse_variables(vars_resp)
        except FigmaClientError as e:
            logger.warning(f"Could not fetch variables: {e}")
            # Try styles as fallback
            try:
                styles_resp = await self.get_file_styles(file_key)
                variables_map = self._parse_styles(styles_resp)
            except FigmaClientError:
                pass

        # 3. Detect components from page children
        children = page_doc.get("children", [])
        components, all_node_ids = self._detect_components_from_tree(
            children, page_bounds
        )

        # 4. Fetch screenshots for all component nodes
        screenshot_paths: Dict[str, str] = {}
        if output_dir and all_node_ids:
            screenshot_paths = await self.download_screenshots(
                file_key, all_node_ids, output_dir
            )

        # Assign screenshot paths to components
        for comp in components:
            nid = comp.get("node_id", "")
            if nid in screenshot_paths:
                comp["screenshot_path"] = screenshot_paths[nid]

        # 5. Build design tokens from variables
        design_tokens = self._variables_to_design_tokens(variables_map)

        # 6. Assemble final export
        export = {
            "version": "1.0",
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "source": "figma",
            "file_key": file_key,
            "file_name": file_name,
            "page_name": page_doc.get("name", ""),
            "page_node_id": page_node_id,
            "page_bounds": page_bounds,
            "variables": variables_map,
            "design_tokens": design_tokens,
            "components": components,
            "asset_urls": {},
            "notes": f"Auto-generated from Figma REST API on {datetime.now(timezone.utc).strftime('%Y-%m-%d')}. Screenshots expire in 30 days.",
        }

        # Optionally write to disk
        if output_dir:
            export_path = os.path.join(output_dir, "design_export.json")
            os.makedirs(output_dir, exist_ok=True)
            with open(export_path, "w", encoding="utf-8") as f:
                json.dump(export, f, ensure_ascii=False, indent=2)
            logger.info(f"generate_design_export: Wrote {export_path}")

        return export

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _parse_variables(self, vars_resp: Dict) -> Dict[str, str]:
        """Parse Figma variables API response into name → value map."""
        result = {}
        meta = vars_resp.get("meta", {})
        variables = meta.get("variables", {})
        collections = meta.get("variableCollections", {})

        for var_id, var_data in variables.items():
            name = var_data.get("name", "")
            resolved = var_data.get("resolvedType", "")
            values_by_mode = var_data.get("valuesByMode", {})

            # Use the first mode's value
            for mode_id, value in values_by_mode.items():
                if resolved == "COLOR" and isinstance(value, dict):
                    # Convert RGBA float dict to hex (round to nearest)
                    r = round(value.get("r", 0) * 255)
                    g = round(value.get("g", 0) * 255)
                    b = round(value.get("b", 0) * 255)
                    result[name] = f"#{r:02X}{g:02X}{b:02X}"
                elif isinstance(value, (int, float)):
                    result[name] = str(value)
                elif isinstance(value, str):
                    result[name] = value
                break  # Only take first mode

        return result

    def _parse_styles(self, styles_resp: Dict) -> Dict[str, str]:
        """Parse Figma styles API response into name → value map (limited)."""
        result = {}
        styles = styles_resp.get("meta", {}).get("styles", [])
        for style in styles:
            name = style.get("name", "")
            style_type = style.get("style_type", "")
            if name:
                # Styles API doesn't return color values directly,
                # but we capture names for documentation
                result[name] = style_type
        return result

    def _detect_components_from_tree(
        self,
        children: List[Dict],
        page_bounds: Dict,
    ) -> Tuple[List[Dict[str, Any]], List[str]]:
        """Detect components from Figma node tree children.

        Uses heuristics based on node type, size, and structure:
        - FRAME/COMPONENT/INSTANCE with visual properties → component
        - Large area relative to page → section/organism
        - Small with few children → atom
        - Skip pure layout groups without visual styles

        Returns:
            Tuple of (components list, all node IDs for screenshot download).
        """
        components = []
        all_node_ids = []
        page_area = page_bounds.get("width", 1) * page_bounds.get("height", 1)

        for child in children:
            comp = self._node_to_component(child, page_area)
            if comp:
                components.append(comp)
                all_node_ids.append(comp["node_id"])

        # Compute neighbors (adjacent components by vertical position)
        components.sort(key=lambda c: c.get("bounds", {}).get("y", 0))
        for i, comp in enumerate(components):
            neighbors = []
            if i > 0:
                neighbors.append(components[i - 1]["name"])
            if i < len(components) - 1:
                neighbors.append(components[i + 1]["name"])
            comp["neighbors"] = neighbors

        return components, all_node_ids

    def _node_to_component(
        self, node: Dict, page_area: float
    ) -> Optional[Dict[str, Any]]:
        """Convert a Figma node to a component descriptor.

        Returns None for nodes that shouldn't be treated as components
        (e.g. invisible, zero-size, pure groups).
        """
        node_type = node.get("type", "")
        name = node.get("name", "Unknown")
        node_id = node.get("id", "")
        visible = node.get("visible", True)

        if not visible:
            return None

        bbox = node.get("absoluteBoundingBox", {})
        if not bbox:
            return None

        width = bbox.get("width", 0)
        height = bbox.get("height", 0)
        if width <= 0 or height <= 0:
            return None

        bounds = {
            "x": bbox.get("x", 0),
            "y": bbox.get("y", 0),
            "width": width,
            "height": height,
        }

        # Determine component type based on size and children
        children = node.get("children", [])
        children_count = len(children)
        area = width * height
        area_ratio = area / page_area if page_area > 0 else 0

        if area_ratio > 0.25:
            comp_type = "section"
        elif children_count > 8:
            comp_type = "organism"
        elif children_count >= 3:
            comp_type = "molecule"
        else:
            comp_type = "atom"

        # Build children summary (first level only, max 10)
        children_summary = []
        for child in children[:10]:
            child_bbox = child.get("absoluteBoundingBox", {})
            child_children = child.get("children", [])
            child_count = len(child_children)

            if child_count > 8:
                child_type = "organism"
            elif child_count >= 3:
                child_type = "molecule"
            else:
                child_type = "atom"

            children_summary.append({
                "name": child.get("name", ""),
                "node_id": child.get("id", ""),
                "type": child_type,
                "bounds": {
                    "x": child_bbox.get("x", 0),
                    "y": child_bbox.get("y", 0),
                    "width": child_bbox.get("width", 0),
                    "height": child_bbox.get("height", 0),
                },
            })

        # Extract text content from all TEXT nodes
        text_content = self._extract_text_content(node)

        # Convert Figma name to PascalCase component name
        component_name = self._to_component_name(name)

        return {
            "node_id": node_id,
            "name": component_name,
            "type": comp_type,
            "bounds": bounds,
            "children_summary": children_summary,
            "text_content": text_content,
            "neighbors": [],  # Filled in by caller
            "screenshot_path": None,
            "notes": f"Figma node '{name}' ({node_type}), {children_count} children",
        }

    def _extract_text_content(self, node: Dict) -> List[str]:
        """Recursively extract all text content from a node tree."""
        texts = []
        if node.get("type") == "TEXT":
            chars = node.get("characters", "")
            if chars and chars.strip():
                texts.append(chars.strip())

        for child in node.get("children", []):
            texts.extend(self._extract_text_content(child))

        return texts

    @staticmethod
    def _to_component_name(figma_name: str) -> str:
        """Convert Figma layer name to PascalCase component name.

        'photo-grid' → 'PhotoGrid'
        'Header 区域' → 'Header'
        'bottom_nav' → 'BottomNav'
        """
        # Remove non-ASCII (Chinese characters etc.)
        name = re.sub(r"[^\x00-\x7f]", " ", figma_name)
        # Split on separators
        parts = re.split(r"[-_\s/]+", name)
        # PascalCase, skip empty parts
        pascal = "".join(p.capitalize() for p in parts if p.strip())
        return pascal or "Component"

    def _variables_to_design_tokens(
        self, variables: Dict[str, str]
    ) -> Dict[str, Any]:
        """Convert raw variable map to structured design_tokens format.

        Classifies variables into colors, fonts, spacing by name patterns.
        """
        tokens: Dict[str, Any] = {
            "colors": {},
            "fonts": {"family": "PingFang SC", "weights": {}, "sizes": {}},
            "spacing": {},
        }

        for name, value in variables.items():
            lower = name.lower()
            # Convert Figma path separators to CSS-friendly names
            css_name = self._to_css_var_name(name)

            if any(k in lower for k in ["color", "fill", "brand", "text&icon", "bg"]):
                tokens["colors"][css_name] = value
            elif any(k in lower for k in ["font", "text-size", "typography"]):
                tokens["fonts"]["sizes"][css_name] = value
            elif any(k in lower for k in ["spacing", "gap", "padding", "margin"]):
                tokens["spacing"][css_name] = value
            elif any(k in lower for k in ["radius", "corner", "round"]):
                tokens["spacing"][css_name] = value
            elif isinstance(value, str) and value.startswith("#"):
                tokens["colors"][css_name] = value

        return tokens

    @staticmethod
    def _to_css_var_name(figma_name: str) -> str:
        """Convert Figma variable name to CSS-friendly name.

        'Text Color/字体_黑60%' → 'text-color-60'
        'Brand-主题色/品牌色 (100%)' → 'brand-100'
        """
        name = figma_name.lower()
        name = re.sub(r"[/\\]", "-", name)
        name = re.sub(r"[_\s]+", "-", name)
        name = re.sub(r"[()%]+", "", name)
        # Remove non-ASCII characters
        name = re.sub(r"[^\x00-\x7f]", "", name)
        name = re.sub(r"-+", "-", name)
        name = name.strip("-")
        return name or "unknown"
