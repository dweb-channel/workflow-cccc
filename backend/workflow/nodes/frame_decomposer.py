"""Node 1: FrameDecomposerNode — Figma node tree to ComponentSpec extraction.

Extracts structural data from Figma node tree into ComponentSpec format
(70% of fields). Applies token reverse mapping and render_hint detection.
"""

import logging
from typing import Any, Dict, List

from .registry import BaseNodeImpl, register_node_type
from .figma_utils import (
    apply_token_reverse_map,
    build_token_reverse_map,
    detect_container_layout,
)
from .figma_spec_builder import (
    _detect_device_type,
    _normalize_bounds,
    figma_node_to_component_spec,
)

logger = logging.getLogger(__name__)


@register_node_type(
    node_type="frame_decomposer",
    display_name="Frame Decomposer",
    description=(
        "Extracts structural data from Figma node tree into ComponentSpec "
        "format (70% of fields). Applies token reverse mapping and "
        "render_hint detection."
    ),
    category="analysis",
    input_schema={
        "type": "object",
        "properties": {
            "figma_node_tree": {
                "type": "object",
                "description": "Raw Figma node tree from get_file_nodes()",
            },
            "design_tokens": {
                "type": "object",
                "description": "Design tokens (colors, fonts, spacing, radii)",
            },
            "page_name": {"type": "string"},
            "page_node_id": {"type": "string"},
            "file_key": {"type": "string"},
            "file_name": {"type": "string"},
            "device_type": {
                "type": "string",
                "enum": ["mobile", "tablet", "desktop"],
            },
            "screenshot_paths": {
                "type": "object",
                "description": "node_id -> screenshot file path mapping",
            },
        },
        "required": ["figma_node_tree"],
    },
    output_schema={
        "type": "object",
        "properties": {
            "components": {
                "type": "array",
                "description": "List of PartialComponentSpec",
            },
            "page": {"type": "object"},
            "design_tokens": {"type": "object"},
            "source": {"type": "object"},
        },
    },
    icon="layers",
    color="#3B82F6",
)
class FrameDecomposerNode(BaseNodeImpl):
    """Node 1: Extracts structural data from Figma node tree.

    Produces PartialComponentSpec for each top-level frame:
    - Fills 70% of fields from Figma API data (layout, sizing, style, typography)
    - Leaves 30% for Node 2 LLM (role, description, interaction)
    - Applies token reverse mapping for ColorValue format
    - Detects render_hint for system elements
    - Computes z_index from children array order
    """

    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        node_tree = inputs.get("figma_node_tree", {})
        design_tokens_raw = inputs.get("design_tokens", {})
        page_name = inputs.get("page_name", "")
        page_node_id = inputs.get("page_node_id", "")
        file_key = inputs.get("file_key", "")
        file_name = inputs.get("file_name", "")
        device_type = inputs.get("device_type")
        screenshot_paths = inputs.get("screenshot_paths", {})

        logger.info(
            "FrameDecomposerNode [%s]: decomposing page '%s' (%s)",
            self.node_id, page_name, page_node_id,
        )

        # Build token reverse map
        reverse_map = build_token_reverse_map(design_tokens_raw)

        # Resolve page document node from various input formats
        page_doc = self._resolve_page_doc(node_tree, page_node_id)

        # Process top-level children
        children = page_doc.get("children", [])
        components: List[Dict] = []
        children_bounds: List[Dict] = []

        for i, child in enumerate(children):
            spec = figma_node_to_component_spec(
                child, z_index=i, reverse_map=reverse_map,
            )
            if spec:
                # Apply token reverse map to all color values
                spec = apply_token_reverse_map(spec, reverse_map)
                # Assign screenshot path if available
                nid = spec["id"]
                if nid in screenshot_paths:
                    spec["screenshot_path"] = screenshot_paths[nid]
                components.append(spec)
                children_bounds.append(spec["bounds"])

        # Normalize canvas-absolute coords -> page-relative
        page_bbox = page_doc.get("absoluteBoundingBox", {})
        origin_x = page_bbox.get("x", 0)
        origin_y = page_bbox.get("y", 0)
        components = [_normalize_bounds(c, origin_x, origin_y) for c in components]
        children_bounds = [c["bounds"] for c in components]

        # Detect page-level layout
        if len(components) <= 1:
            page_layout: Dict[str, Any] = {"type": "flex", "direction": "column"}
        else:
            page_layout = detect_container_layout(page_doc, children_bounds)
        page_width = page_bbox.get("width", 0)
        page_height = page_bbox.get("height", 0)

        page = {
            "name": page_name or page_doc.get("name", ""),
            "node_id": page_node_id or page_doc.get("id", ""),
            "device": {
                "type": device_type or _detect_device_type(page_width),
                "width": page_width,
                "height": page_height,
            },
            "description": "",  # Node 2 fills
            "responsive_strategy": "fixed-width",  # Node 2 may override
            "layout": page_layout,
        }

        # Format design tokens for schema output
        schema_tokens = self._format_design_tokens(design_tokens_raw)

        logger.info(
            "FrameDecomposerNode [%s]: decomposed %d components, "
            "page layout=%s",
            self.node_id, len(components), page_layout.get("type"),
        )

        return {
            "components": components,
            "page": page,
            "design_tokens": schema_tokens,
            "source": {
                "tool": "figma",
                "file_key": file_key,
                "file_name": file_name,
            },
        }

    @staticmethod
    def _resolve_page_doc(node_tree: Dict, page_node_id: str) -> Dict:
        """Resolve the page document node from various input formats.

        Supports:
        1. Raw get_file_nodes() response: {nodes: {node_id: {document: {...}}}}
        2. Direct document node: {type: "FRAME", children: [...]}
        3. Design export format: {components: [...], page_bounds: {...}}
        """
        # Format 1: Raw API response
        if "nodes" in node_tree:
            page_data = node_tree["nodes"].get(page_node_id, {})
            doc = page_data.get("document", {})
            if doc:
                return doc
            # Try first node if specific ID not found
            for nid, ndata in node_tree["nodes"].items():
                return ndata.get("document", {})

        # Format 2: Direct document node (has 'type' and 'children')
        if "type" in node_tree and "children" in node_tree:
            return node_tree

        # Format 3: Design export (has 'components' at top level)
        if "components" in node_tree and "page_bounds" in node_tree:
            logger.warning(
                "FrameDecomposerNode: received design_export format -- "
                "layout/sizing/style fields will be incomplete (no raw "
                "Figma properties). Use raw get_file_nodes() response "
                "for full spec extraction."
            )
            return node_tree

        return node_tree

    @staticmethod
    def _format_design_tokens(raw_tokens: Dict) -> Dict[str, Any]:
        """Format design tokens for schema output.

        Converts internal token format to the schema's design_tokens structure:
        {colors: {...}, typography: {font_family, scale}, spacing: {...}, radii: {...}}
        """
        result: Dict[str, Any] = {}

        colors = raw_tokens.get("colors", {})
        if colors:
            result["colors"] = colors

        # Convert fonts structure to schema typography format
        fonts = raw_tokens.get("fonts", {})
        if fonts:
            typography: Dict[str, Any] = {}
            if fonts.get("family"):
                typography["font_family"] = fonts["family"]
            sizes = fonts.get("sizes", {})
            if sizes:
                scale = {}
                for name, size in sizes.items():
                    try:
                        scale[name] = {
                            "size": float(size) if isinstance(size, str) else size
                        }
                    except (ValueError, TypeError):
                        pass
                if scale:
                    typography["scale"] = scale
            if typography:
                result["typography"] = typography

        spacing = raw_tokens.get("spacing", {})
        if spacing:
            spacing_vals: Dict[str, Any] = {}
            radii_vals: Dict[str, Any] = {}
            for name, val in spacing.items():
                try:
                    num_val = float(val) if isinstance(val, str) else val
                except (ValueError, TypeError):
                    continue
                if "radius" in name.lower() or "round" in name.lower():
                    radii_vals[name] = num_val
                else:
                    spacing_vals[name] = num_val
            if spacing_vals:
                result["spacing"] = spacing_vals
            if radii_vals:
                result["radii"] = radii_vals

        return result
