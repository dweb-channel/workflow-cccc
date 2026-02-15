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
        timeout: float = 60.0,
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

    async def get_design_tokens(self, file_key: str) -> Dict[str, Any]:
        """Fetch and parse design tokens from a Figma file's variables.

        Combines get_file_variables + variable parsing + token classification
        into a single public API.

        Args:
            file_key: Figma file key.

        Returns:
            Structured design_tokens dict with colors, fonts, spacing keys.
        """
        vars_resp = await self.get_file_variables(file_key)
        variables_map = self._parse_variables(vars_resp)
        return self._variables_to_design_tokens(variables_map)

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
                async with httpx.AsyncClient(timeout=60.0) as dl_client:
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

    # ------------------------------------------------------------------
    # Interaction context extraction (D5)
    # ------------------------------------------------------------------

    # Node types that indicate visual annotations (arrows, lines, connectors)
    _VISUAL_ANNOTATION_TYPES = frozenset({
        "LINE", "ARROW", "VECTOR", "BOOLEAN_OPERATION", "STAR", "POLYGON",
    })

    def _extract_interaction_context(
        self,
        node: Dict,
    ) -> Dict[str, Any]:
        """Extract interaction context from an annotation/spec frame.

        Extracts text content from all TEXT nodes and detects whether the
        frame contains visual annotation elements (arrows, lines, vectors)
        that would benefit from a screenshot for vision-based understanding.

        Args:
            node: Figma node dict (typically an interaction spec frame).

        Returns:
            Dict with:
                - text_content: list of extracted text strings
                - has_visual_annotations: True if LINE/ARROW/VECTOR nodes found
                - visual_annotation_types: set of detected annotation node types
                - node_id: the frame's node ID
                - name: the frame's name
        """
        text_content = self._extract_text_content(node)
        visual_types = self._detect_visual_annotations(node)

        return {
            "text_content": text_content,
            "has_visual_annotations": len(visual_types) > 0,
            "visual_annotation_types": sorted(visual_types),
            "node_id": node.get("id", ""),
            "name": node.get("name", ""),
        }

    def _detect_visual_annotations(self, node: Dict) -> set:
        """Recursively detect visual annotation node types in a subtree.

        Looks for LINE, ARROW, VECTOR, BOOLEAN_OPERATION, STAR, POLYGON
        nodes that typically indicate design annotations (arrows pointing
        between elements, flow diagrams, connector lines).

        Args:
            node: Figma node dict to scan.

        Returns:
            Set of detected annotation type strings.
        """
        found: set = set()
        node_type = node.get("type", "")
        if node_type in self._VISUAL_ANNOTATION_TYPES:
            found.add(node_type)

        for child in node.get("children", []):
            found.update(self._detect_visual_annotations(child))

        return found

    async def extract_interaction_contexts(
        self,
        file_key: str,
        spec_nodes: List[Dict],
        output_dir: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Extract interaction context from multiple spec frames.

        For each spec frame, extracts text content and detects visual
        annotations. If visual annotations are detected and output_dir
        is provided, downloads a screenshot for vision-based processing.

        Args:
            file_key: Figma file key.
            spec_nodes: List of node dicts (must have 'id' and 'children').
            output_dir: If provided, downloads screenshots for frames
                        with visual annotations (scale=1 for clarity).

        Returns:
            List of interaction context dicts, each containing:
                - text_content, has_visual_annotations, visual_annotation_types
                - node_id, name
                - screenshot_path (if visual annotations detected and output_dir set)
        """
        results = []
        needs_screenshot_ids = []

        for node in spec_nodes:
            ctx = self._extract_interaction_context(node)
            results.append(ctx)
            if ctx["has_visual_annotations"]:
                needs_screenshot_ids.append(ctx["node_id"])

        # Download screenshots for frames with visual annotations
        if output_dir and needs_screenshot_ids:
            screenshots_dir = os.path.join(output_dir, "interaction_screenshots")
            os.makedirs(screenshots_dir, exist_ok=True)

            try:
                image_urls = await self.get_node_images(
                    file_key, needs_screenshot_ids, fmt="png", scale=1
                )
                client = await self._get_client()
                for node_id, url in image_urls.items():
                    if not url:
                        continue
                    safe_id = node_id.replace(":", "_")
                    filename = f"{safe_id}.png"
                    filepath = os.path.join(screenshots_dir, filename)
                    rel_path = f"interaction_screenshots/{filename}"

                    try:
                        async with httpx.AsyncClient(timeout=60.0) as dl_client:
                            img_resp = await dl_client.get(url)
                        if img_resp.status_code == 200:
                            with open(filepath, "wb") as f:
                                f.write(img_resp.content)
                            # Attach screenshot path to matching result
                            for ctx in results:
                                if ctx["node_id"] == node_id:
                                    ctx["screenshot_path"] = rel_path
                                    break
                            logger.info(
                                f"extract_interaction_contexts: screenshot {node_id} "
                                f"→ {rel_path} ({len(img_resp.content)} bytes)"
                            )
                    except Exception as e:
                        logger.warning(
                            f"extract_interaction_contexts: screenshot download "
                            f"failed for {node_id}: {e}"
                        )
            except FigmaClientError as e:
                logger.warning(f"extract_interaction_contexts: image fetch failed: {e}")

        logger.info(
            f"extract_interaction_contexts: {len(results)} frames processed, "
            f"{len(needs_screenshot_ids)} with visual annotations"
        )
        return results

    # ------------------------------------------------------------------
    # Smart page scan + classification (D1)
    # ------------------------------------------------------------------

    # Common mobile screen widths (tolerance ±10px)
    _MOBILE_WIDTHS = {360, 375, 390, 393, 412, 414, 428, 430}
    # Tablet widths
    _TABLET_WIDTHS = {744, 768, 810, 820, 834}
    # Desktop minimum width
    _DESKTOP_MIN_WIDTH = 1024
    # Minimum height for a valid screen frame
    _SCREEN_MIN_HEIGHT = 500
    # Width tolerance for screen matching
    _WIDTH_TOLERANCE = 10

    # Keywords that indicate non-UI content (case-insensitive matching)
    _EXCLUDE_KEYWORDS = frozenset({
        "参考", "取色", "核查", "备注", "old", "archive", "旧版",
        "废弃", "deprecated", "draft", "temp",
    })
    # Keywords that indicate interaction specs
    _INTERACTION_KEYWORDS = frozenset({
        "交互", "说明", "流程", "动画", "效果", "标注", "annotation",
        "interaction", "spec", "flow", "transition",
    })
    # Keywords that indicate design system content
    _DESIGN_SYSTEM_KEYWORDS = frozenset({
        "取色", "颜色", "色板", "color", "palette", "token",
        "typography", "字体", "spacing", "间距", "style guide",
    })

    def _classify_frame_by_rules(
        self,
        node: Dict,
    ) -> Dict[str, Any]:
        """Classify a single top-level frame using rule-based heuristics.

        Returns a classification dict with:
            - node_id, name, size, bounds
            - classification: 'ui_screen' | 'interaction_spec' | 'design_system' | 'excluded' | 'unknown'
            - confidence: 0.0-1.0
            - device_type: 'mobile' | 'tablet' | 'desktop' | None
            - reason: explanation of classification decision
        """
        name = node.get("name", "")
        node_id = node.get("id", "")
        node_type = node.get("type", "")
        visible = node.get("visible", True)
        bbox = node.get("absoluteBoundingBox", {})
        w = bbox.get("width", 0)
        h = bbox.get("height", 0)
        lower_name = name.lower()

        base = {
            "node_id": node_id,
            "name": name,
            "size": f"{int(w)}×{int(h)}",
            "bounds": {
                "x": bbox.get("x", 0),
                "y": bbox.get("y", 0),
                "width": w,
                "height": h,
            },
        }

        # Invisible → excluded
        if not visible:
            return {
                **base,
                "classification": "excluded",
                "confidence": 0.99,
                "device_type": None,
                "reason": "invisible",
            }

        # Zero-size → excluded
        if w <= 0 or h <= 0:
            return {
                **base,
                "classification": "excluded",
                "confidence": 0.99,
                "device_type": None,
                "reason": "zero_size",
            }

        # --- Keyword-based exclusion (highest priority) ---
        for kw in self._EXCLUDE_KEYWORDS:
            if kw in lower_name:
                return {
                    **base,
                    "classification": "excluded",
                    "confidence": 0.9,
                    "device_type": None,
                    "reason": f"keyword_match:{kw}",
                }

        # --- Size-based classification (before soft keywords) ---
        # Size is a stronger signal than name keywords like "效果"/"说明"

        # Check mobile screen sizes
        is_mobile = (
            any(abs(w - mw) <= self._WIDTH_TOLERANCE for mw in self._MOBILE_WIDTHS)
            and h >= self._SCREEN_MIN_HEIGHT
        )
        if is_mobile:
            return {
                **base,
                "classification": "ui_screen",
                "confidence": 0.95,
                "device_type": "mobile",
                "reason": f"mobile_size:{int(w)}×{int(h)}",
            }

        # Check tablet sizes
        is_tablet = (
            any(abs(w - tw) <= self._WIDTH_TOLERANCE for tw in self._TABLET_WIDTHS)
            and h >= self._SCREEN_MIN_HEIGHT
        )
        if is_tablet:
            return {
                **base,
                "classification": "ui_screen",
                "confidence": 0.9,
                "device_type": "tablet",
                "reason": f"tablet_size:{int(w)}×{int(h)}",
            }

        # Check desktop sizes
        if w >= self._DESKTOP_MIN_WIDTH and h >= self._SCREEN_MIN_HEIGHT:
            return {
                **base,
                "classification": "ui_screen",
                "confidence": 0.8,
                "device_type": "desktop",
                "reason": f"desktop_size:{int(w)}×{int(h)}",
            }

        # --- Extreme aspect ratio → excluded (banners, strips) ---
        if w > 0 and h > 0:
            aspect = h / w
            if aspect < 0.2 and w >= 800:
                return {
                    **base,
                    "classification": "excluded",
                    "confidence": 0.7,
                    "device_type": None,
                    "reason": f"wide_banner:{int(w)}×{int(h)}",
                }

        # --- Soft keyword classification (after size check) ---

        # Design system keywords
        for kw in self._DESIGN_SYSTEM_KEYWORDS:
            if kw in lower_name:
                return {
                    **base,
                    "classification": "design_system",
                    "confidence": 0.85,
                    "device_type": None,
                    "reason": f"keyword_match:{kw}",
                }

        # Interaction spec keywords
        for kw in self._INTERACTION_KEYWORDS:
            if kw in lower_name:
                return {
                    **base,
                    "classification": "interaction_spec",
                    "confidence": 0.85,
                    "device_type": None,
                    "reason": f"keyword_match:{kw}",
                }

        # --- Fallback: unknown (needs LLM classification) ---
        return {
            **base,
            "classification": "unknown",
            "confidence": 0.0,
            "device_type": None,
            "reason": "no_rule_match",
        }

    def _associate_specs_to_screens(
        self,
        screens: List[Dict],
        specs: List[Dict],
    ) -> None:
        """Associate interaction specs to their nearest UI screen by spatial proximity.

        Uses center-to-center distance between bounding boxes.
        Also tries name prefix matching as a secondary signal.

        Mutates specs in-place: adds 'related_to' field with the
        nearest screen's node_id and name.
        """
        if not screens or not specs:
            return

        for spec in specs:
            spec_bounds = spec.get("bounds", {})
            spec_cx = spec_bounds.get("x", 0) + spec_bounds.get("width", 0) / 2
            spec_cy = spec_bounds.get("y", 0) + spec_bounds.get("height", 0) / 2
            spec_name = spec.get("name", "").lower()

            best_screen = None
            best_distance = float("inf")

            for screen in screens:
                scr_bounds = screen.get("bounds", {})
                scr_cx = scr_bounds.get("x", 0) + scr_bounds.get("width", 0) / 2
                scr_cy = scr_bounds.get("y", 0) + scr_bounds.get("height", 0) / 2
                scr_name = screen.get("name", "").lower()

                # Euclidean distance between centers
                dist = ((spec_cx - scr_cx) ** 2 + (spec_cy - scr_cy) ** 2) ** 0.5

                # Name prefix match bonus: reduce distance if names share prefix
                # e.g. "首页-交互说明" and "首页"
                name_bonus = 0
                if scr_name and spec_name:
                    # Check if screen name is a prefix of spec name (or vice versa)
                    shorter = min(scr_name, spec_name, key=len)
                    longer = max(scr_name, spec_name, key=len)
                    if longer.startswith(shorter) and len(shorter) >= 2:
                        name_bonus = 5000  # Strong bonus

                effective_dist = dist - name_bonus

                if effective_dist < best_distance:
                    best_distance = effective_dist
                    best_screen = screen

            if best_screen:
                spec["related_to"] = {
                    "node_id": best_screen["node_id"],
                    "name": best_screen["name"],
                }

    async def resolve_to_page(
        self,
        file_key: str,
        node_id: str,
        node_doc: Dict,
    ) -> Optional[Dict[str, str]]:
        """Resolve a small/nested node to its parent page for scanning.

        Fetches the file structure at depth=2, then finds which page
        contains the given node by checking spatial containment of
        top-level frames' bounding boxes.

        Args:
            file_key: Figma file key.
            node_id: The target node ID.
            node_doc: The node's document dict (from get_file_nodes).

        Returns:
            Dict with {page_id, page_name} if resolved, or None if
            the node is already a page or resolution failed.
        """
        node_type = node_doc.get("type", "")
        if node_type in ("PAGE", "CANVAS"):
            return None  # Already a page

        bbox = node_doc.get("absoluteBoundingBox", {})
        target_w = bbox.get("width", 0)
        target_h = bbox.get("height", 0)

        if target_w >= 300 and target_h >= 600:
            return None  # Large enough to scan directly

        target_x = bbox.get("x", 0)
        target_y = bbox.get("y", 0)

        # Fetch file structure: Document → Pages → Top-level frames
        try:
            file_data = await self._get(
                f"/v1/files/{file_key}", params={"depth": "2"}
            )
        except FigmaClientError as e:
            logger.warning(f"resolve_to_page: failed to fetch file structure: {e}")
            return None

        document = file_data.get("document", {})
        pages = document.get("children", [])

        if not pages:
            return None

        # Search: find the page whose top-level frame spatially contains our node
        for page in pages:
            for frame in page.get("children", []):
                frame_bbox = frame.get("absoluteBoundingBox", {})
                if not frame_bbox:
                    continue
                fx = frame_bbox.get("x", 0)
                fy = frame_bbox.get("y", 0)
                fw = frame_bbox.get("width", 0)
                fh = frame_bbox.get("height", 0)

                if (fx <= target_x <= fx + fw and
                        fy <= target_y <= fy + fh):
                    page_id = page.get("id", "")
                    page_name = page.get("name", "")
                    logger.info(
                        f"resolve_to_page: {node_id} ({int(target_w)}×{int(target_h)}) "
                        f"→ page '{page_name}' ({page_id})"
                    )
                    return {"page_id": page_id, "page_name": page_name}

        # Fallback: single-page file
        if len(pages) == 1:
            page_id = pages[0].get("id", "")
            page_name = pages[0].get("name", "")
            logger.info(
                f"resolve_to_page: single-page fallback → '{page_name}' ({page_id})"
            )
            return {"page_id": page_id, "page_name": page_name}

        return None

    async def scan_and_classify_frames(
        self,
        file_key: str,
        page_node_id: str,
        llm_classifier: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """Scan a Figma page and classify all top-level frames.

        Phase 1: Rule-based pre-filtering (size, keywords, visibility)
        Phase 2: LLM classification for low-confidence items (if classifier provided)
        Phase 3: Spatial proximity association (interaction specs → UI screens)

        Also recurses into SECTION nodes (depth=2) to find nested frames.

        Args:
            file_key: Figma file key.
            page_node_id: Root page node ID.
            llm_classifier: Optional async callable for LLM classification.
                            Signature: async (frames_summary: List[Dict]) -> List[Dict]
                            If None, unknown frames stay as 'unknown'.

        Returns:
            Dict with:
                - file_key, page_name
                - candidates: UI screen frames
                - interaction_specs: interaction annotation frames
                - design_system: design system/token frames
                - excluded: filtered out frames
                - unknown: frames that couldn't be classified (only if no LLM)
        """
        # Fetch page tree with depth=2 for section recursion
        data = await self.get_file_nodes(file_key, [page_node_id])
        nodes_data = data.get("nodes", {})
        page_data = nodes_data.get(page_node_id, {})
        page_doc = page_data.get("document", {})
        page_name = page_doc.get("name", "")

        children = page_doc.get("children", [])

        # Check if target node is too small to be a page/screen
        warnings: List[str] = []
        target_bbox = page_doc.get("absoluteBoundingBox", {})
        target_w = target_bbox.get("width", 0)
        target_h = target_bbox.get("height", 0)
        target_type = page_doc.get("type", "")
        if target_type not in ("PAGE", "CANVAS") and (target_w < 300 or target_h < 600):
            warnings.append(
                f"当前节点 \"{page_name}\" 尺寸为 {int(target_w)}×{int(target_h)}，"
                f"可能不是完整的 UI 页面。建议选择更大的 frame 或使用页面级 URL（不带 node-id）。"
            )
            logger.warning(
                f"scan_and_classify_frames: target node {page_node_id} is small "
                f"({int(target_w)}×{int(target_h)}), may not be a page"
            )

        # Collect all top-level frames (recurse into SECTIONs)
        all_frames = []
        for child in children:
            child_type = child.get("type", "")
            if child_type == "SECTION":
                section_name = child.get("name", "")
                # Recurse into section children
                for nested in child.get("children", []):
                    nested_classified = self._classify_frame_by_rules(nested)
                    nested_classified["section"] = section_name
                    all_frames.append((nested, nested_classified))
            else:
                classified = self._classify_frame_by_rules(child)
                classified["section"] = None
                all_frames.append((child, classified))

        # Phase 2: LLM classification for unknowns
        unknowns = [(node, clf) for node, clf in all_frames if clf["classification"] == "unknown"]
        if unknowns and llm_classifier:
            try:
                # Build summary for LLM
                summary = []
                for node, clf in unknowns:
                    child_types = [c.get("type", "") for c in node.get("children", [])[:20]]
                    text_preview = self._extract_text_content(node)[:5]
                    summary.append({
                        "node_id": clf["node_id"],
                        "name": clf["name"],
                        "size": clf["size"],
                        "bounds": clf["bounds"],
                        "section": clf["section"],
                        "child_count": len(node.get("children", [])),
                        "child_types": child_types,
                        "text_preview": text_preview,
                    })

                llm_results = await llm_classifier(summary)

                # Merge LLM results back
                llm_map = {r["node_id"]: r for r in llm_results}
                for node, clf in unknowns:
                    if clf["node_id"] in llm_map:
                        llm_result = llm_map[clf["node_id"]]
                        clf["classification"] = llm_result.get("classification", "unknown")
                        clf["confidence"] = llm_result.get("confidence", 0.5)
                        clf["reason"] = f"llm:{llm_result.get('reason', '')}"
            except Exception as e:
                logger.warning(f"scan_and_classify_frames: LLM classification failed: {e}")
                # Fallback: leave as unknown

        # Categorize results
        candidates = []
        interaction_specs = []
        design_system = []
        excluded = []
        unknown = []

        for node, clf in all_frames:
            # Enrich with text content for interaction specs
            if clf["classification"] == "interaction_spec":
                clf["text_content"] = self._extract_text_content(node)
            classification = clf["classification"]
            if classification == "ui_screen":
                candidates.append(clf)
            elif classification == "interaction_spec":
                interaction_specs.append(clf)
            elif classification == "design_system":
                design_system.append(clf)
            elif classification == "excluded":
                excluded.append(clf)
            else:
                unknown.append(clf)

        # Phase 3: Associate interaction specs to nearest UI screens
        self._associate_specs_to_screens(candidates, interaction_specs)

        logger.info(
            f"scan_and_classify_frames: {len(candidates)} screens, "
            f"{len(interaction_specs)} specs, {len(design_system)} design system, "
            f"{len(excluded)} excluded, {len(unknown)} unknown"
        )

        return {
            "file_key": file_key,
            "page_name": page_name,
            "candidates": candidates,
            "interaction_specs": interaction_specs,
            "design_system": design_system,
            "excluded": excluded,
            "unknown": unknown,
            "warnings": warnings,
        }

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
