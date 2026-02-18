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
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx

from .figma_classifiers import (
    associate_specs_to_screens,
    classify_frame_by_rules,
    detect_components_from_tree,
    extract_interaction_context,
    extract_text_content,
    parse_styles,
    parse_variables,
    variables_to_design_tokens,
)

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

    async def get_file_version(self, file_key: str) -> Optional[str]:
        """Fetch the current version of a Figma file.

        GET /v1/files/:key (depth=1 to minimize payload)
        """
        try:
            data = await self._get(
                f"/v1/files/{file_key}", params={"depth": "1"}
            )
            version = data.get("version")
            if version:
                logger.info(f"get_file_version: file={file_key}, version={version}")
            return version
        except FigmaClientError as e:
            logger.warning(f"get_file_version: failed for {file_key}: {e}")
            return None

    async def get_file_nodes(
        self,
        file_key: str,
        node_ids: List[str],
    ) -> Dict[str, Any]:
        """Fetch specific nodes from a Figma file.

        GET /v1/files/:key/nodes?ids=...
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
        version: Optional[str] = None,
    ) -> Dict[str, Optional[str]]:
        """Render node screenshots via Figma's image export API.

        GET /v1/images/:key?ids=...&format=png&scale=2&version=...
        """
        if version is None:
            version = await self.get_file_version(file_key)

        ids_param = ",".join(node_ids)
        params: Dict[str, str] = {
            "ids": ids_param,
            "format": fmt,
            "scale": str(scale),
        }
        if version:
            params["version"] = version

        data = await self._get(
            f"/v1/images/{file_key}",
            params=params,
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
        """Fetch published styles from a Figma file."""
        data = await self._get(f"/v1/files/{file_key}/styles")
        styles = data.get("meta", {}).get("styles", [])
        logger.info(f"get_file_styles: file={file_key}, styles_count={len(styles)}")
        return data

    async def get_file_variables(
        self,
        file_key: str,
    ) -> Dict[str, Any]:
        """Fetch local variables from a Figma file."""
        data = await self._get(f"/v1/files/{file_key}/variables/local")
        logger.info(f"get_file_variables: file={file_key}")
        return data

    async def get_design_tokens(self, file_key: str) -> Dict[str, Any]:
        """Fetch and parse design tokens from a Figma file's variables."""
        vars_resp = await self.get_file_variables(file_key)
        vars_map = parse_variables(vars_resp)
        return variables_to_design_tokens(vars_map)

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
        version: Optional[str] = None,
    ) -> Dict[str, str]:
        """Download node screenshots to disk.

        1. Calls get_node_images() to get render URLs
        2. Downloads each image to {output_dir}/screenshots/{node_id}.{fmt}
        """
        screenshots_dir = os.path.join(output_dir, "screenshots")
        os.makedirs(screenshots_dir, exist_ok=True)

        image_urls = await self.get_node_images(
            file_key, node_ids, fmt=fmt, scale=scale, version=version,
        )

        client = await self._get_client()
        downloaded: Dict[str, str] = {}

        for node_id, url in image_urls.items():
            if not url:
                logger.warning(f"download_screenshots: No image URL for node {node_id}")
                continue

            safe_id = node_id.replace(":", "_")
            filename = f"{safe_id}.{fmt}"
            filepath = os.path.join(screenshots_dir, filename)
            rel_path = f"screenshots/{filename}"

            try:
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
        """Generate a design_export.json-compatible structure from Figma API."""
        # 1. Fetch the page node tree
        nodes_resp = await self.get_file_nodes(file_key, [page_node_id])
        nodes_data = nodes_resp.get("nodes", {})

        page_data = nodes_data.get(page_node_id, {})
        page_doc = page_data.get("document", {})

        file_name = nodes_resp.get("name", "")

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
            variables_map = parse_variables(vars_resp)
        except FigmaClientError as e:
            logger.warning(f"Could not fetch variables: {e}")
            try:
                styles_resp = await self.get_file_styles(file_key)
                variables_map = parse_styles(styles_resp)
            except FigmaClientError:
                pass

        # 3. Detect components from page children
        children = page_doc.get("children", [])
        components, all_node_ids = detect_components_from_tree(
            children, page_bounds
        )

        # 4. Fetch screenshots for all component nodes
        screenshot_paths: Dict[str, str] = {}
        if output_dir and all_node_ids:
            screenshot_paths = await self.download_screenshots(
                file_key, all_node_ids, output_dir
            )

        for comp in components:
            nid = comp.get("node_id", "")
            if nid in screenshot_paths:
                comp["screenshot_path"] = screenshot_paths[nid]

        # 5. Build design tokens from variables
        design_tokens = variables_to_design_tokens(variables_map)

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

        if output_dir:
            export_path = os.path.join(output_dir, "design_export.json")
            os.makedirs(output_dir, exist_ok=True)
            with open(export_path, "w", encoding="utf-8") as f:
                json.dump(export, f, ensure_ascii=False, indent=2)
            logger.info(f"generate_design_export: Wrote {export_path}")

        return export

    # ------------------------------------------------------------------
    # Interaction context extraction (D5)
    # ------------------------------------------------------------------

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
        """
        results = []
        needs_screenshot_ids = []

        for node in spec_nodes:
            ctx = extract_interaction_context(node)
            results.append(ctx)
            if ctx["has_visual_annotations"]:
                needs_screenshot_ids.append(ctx["node_id"])

        if output_dir and needs_screenshot_ids:
            screenshots_dir = os.path.join(output_dir, "interaction_screenshots")
            os.makedirs(screenshots_dir, exist_ok=True)

            try:
                image_urls = await self.get_node_images(
                    file_key, needs_screenshot_ids, fmt="png", scale=1
                )
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

    async def resolve_to_page(
        self,
        file_key: str,
        node_id: str,
        node_doc: Dict,
    ) -> Optional[Dict[str, str]]:
        """Resolve a small/nested node to its parent page for scanning."""
        node_type = node_doc.get("type", "")
        if node_type in ("PAGE", "CANVAS"):
            return None

        bbox = node_doc.get("absoluteBoundingBox", {})
        target_w = bbox.get("width", 0)
        target_h = bbox.get("height", 0)

        if target_w >= 300 and target_h >= 600:
            return None

        target_x = bbox.get("x", 0)
        target_y = bbox.get("y", 0)

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
        """
        data = await self.get_file_nodes(file_key, [page_node_id])
        nodes_data = data.get("nodes", {})
        page_data = nodes_data.get(page_node_id, {})
        page_doc = page_data.get("document", {})
        page_name = page_doc.get("name", "")

        children = page_doc.get("children", [])

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
                for nested in child.get("children", []):
                    nested_classified = classify_frame_by_rules(nested)
                    nested_classified["section"] = section_name
                    all_frames.append((nested, nested_classified))
            else:
                classified = classify_frame_by_rules(child)
                classified["section"] = None
                all_frames.append((child, classified))

        # Phase 2: LLM classification for unknowns
        unknowns = [(node, clf) for node, clf in all_frames if clf["classification"] == "unknown"]
        if unknowns and llm_classifier:
            try:
                summary = []
                for node, clf in unknowns:
                    child_types = [c.get("type", "") for c in node.get("children", [])[:20]]
                    text_preview = extract_text_content(node)[:5]
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

                llm_map = {r["node_id"]: r for r in llm_results}
                for node, clf in unknowns:
                    if clf["node_id"] in llm_map:
                        llm_result = llm_map[clf["node_id"]]
                        clf["classification"] = llm_result.get("classification", "unknown")
                        clf["confidence"] = llm_result.get("confidence", 0.5)
                        clf["reason"] = f"llm:{llm_result.get('reason', '')}"
            except Exception as e:
                logger.warning(f"scan_and_classify_frames: LLM classification failed: {e}")

        # Categorize results
        candidates = []
        interaction_specs = []
        design_system = []
        excluded = []
        unknown = []

        for node, clf in all_frames:
            if clf["classification"] == "interaction_spec":
                clf["text_content"] = extract_text_content(node)
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
        associate_specs_to_screens(candidates, interaction_specs)

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
