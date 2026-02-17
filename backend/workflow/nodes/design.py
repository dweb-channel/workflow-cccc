"""
Design-to-Spec Pipeline Nodes

DesignAnalyzerNode - Analyzes design files, extracts component tree + tokens.
This is the core node for the design-to-spec pipeline, converting Figma designs
into structured component specifications with precise layout/style data.
"""

import json
import logging
import os
import re
from typing import Any, Dict, List, Optional

from .registry import BaseNodeImpl, register_node_type

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Module helpers
# ---------------------------------------------------------------------------

def _get_bounds(node: Dict[str, Any]) -> Dict[str, float]:
    """Extract bounding box from Figma node (handles both absoluteBoundingBox and bounds)."""
    # Figma REST API format
    if "absoluteBoundingBox" in node:
        bb = node["absoluteBoundingBox"]
        return {
            "x": bb.get("x", 0),
            "y": bb.get("y", 0),
            "width": bb.get("width", 0),
            "height": bb.get("height", 0),
        }
    # Pre-extracted format (design_export.json)
    if "bounds" in node:
        return node["bounds"]
    # Direct x/y/width/height
    if "width" in node:
        return {
            "x": node.get("x", 0),
            "y": node.get("y", 0),
            "width": node.get("width", 0),
            "height": node.get("height", 0),
        }
    return {}


# ---------------------------------------------------------------------------
# Node: DesignAnalyzerNode
# ---------------------------------------------------------------------------

@register_node_type(
    node_type="design_analyzer",
    display_name="Design Analyzer",
    description="Analyzes design files via MCP, extracts component tree, design tokens, and spatial relationships",
    category="analysis",
    input_schema={
        "type": "object",
        "properties": {
            "design_source": {
                "type": "string",
                "description": "Design source: 'figma' or 'pencil'",
                "enum": ["figma", "pencil"],
            },
            "design_file": {
                "type": "string",
                "description": "Figma file URL or Pencil .pen file path",
            },
            "design_node_id": {
                "type": "string",
                "description": "Optional: specific node/frame ID to analyze (if omitted, analyzes entire file)",
            },
            "granularity": {
                "type": "string",
                "description": "Component detection granularity: 'auto' (AI decides), 'conservative' (fewer, larger chunks), 'aggressive' (more, smaller chunks)",
                "enum": ["auto", "conservative", "aggressive"],
            },
        },
        "required": ["design_source", "design_file"],
    },
    output_schema={
        "type": "object",
        "properties": {
            "components": {
                "type": "array",
                "description": "Ordered list of detected components (implementation order)",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "node_id": {"type": "string"},
                        "type": {
                            "type": "string",
                            "enum": ["atom", "molecule", "organism", "section"],
                        },
                        "bounds": {
                            "type": "object",
                            "properties": {
                                "x": {"type": "number"},
                                "y": {"type": "number"},
                                "width": {"type": "number"},
                                "height": {"type": "number"},
                            },
                        },
                        "neighbors": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Names of spatially adjacent components",
                        },
                        "children_count": {"type": "integer"},
                        "is_reusable": {"type": "boolean"},
                        "reuse_count": {"type": "integer"},
                    },
                },
            },
            "tokens": {
                "type": "object",
                "description": "Extracted design tokens",
                "properties": {
                    "colors": {"type": "object"},
                    "fonts": {"type": "object"},
                    "spacing": {"type": "object"},
                    "border_radius": {"type": "object"},
                    "shadows": {"type": "object"},
                },
            },
            "skeleton_structure": {
                "type": "object",
                "description": "Page-level layout structure (grid/flex hierarchy)",
            },
            "total_components": {"type": "integer"},
            "design_screenshot_base64": {
                "type": "string",
                "description": "Full page design screenshot for final comparison",
            },
        },
    },
    icon="scan",
    color="#8B5CF6",
)
class DesignAnalyzerNode(BaseNodeImpl):
    """
    Analyzes a design file and produces:
    1. Ordered component list with spatial relationships
    2. Design tokens (colors, fonts, spacing)
    3. Skeleton structure for layout generation
    4. Reference screenshots for visual comparison

    Implementation strategy:
    - Step 1: Read design tree via MCP (deterministic)
    - Step 2: Extract design tokens via MCP get_variables (deterministic)
    - Step 3: Identify component boundaries via AI semantic analysis
    - Step 4: Compute spatial adjacency graph
    - Step 5: Topological sort for implementation order (atoms first)
    """

    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        design_source = self.config.get("design_source") or inputs.get("design_source", "json")
        design_file = self._render_config("design_file", inputs) or inputs.get("design_file", "")
        design_node_id = self.config.get("design_node_id") or inputs.get("design_node_id")
        granularity = self.config.get("granularity", "auto")

        logger.info(
            "DesignAnalyzerNode [%s]: analyzing %s file=%s node=%s granularity=%s",
            self.node_id, design_source, design_file, design_node_id, granularity,
        )

        if design_source == "json":
            # --- POC path: consume pre-extracted JSON ---
            return await self._execute_from_json(design_file, granularity, inputs)

        # --- MCP path (future): live Figma/Pencil ---
        node_tree = await self._fetch_design_tree(design_source, design_file, design_node_id)
        tokens = await self._extract_tokens(design_source, design_file)
        components = await self._detect_components(node_tree, granularity, inputs)
        components = self._compute_spatial_neighbors(components)
        components = self._sort_by_implementation_order(components)
        screenshot = await self._get_design_screenshot(design_source, design_file, design_node_id)

        return {
            "components": components,
            "tokens": tokens,
            "skeleton_structure": self._extract_skeleton(node_tree),
            "total_components": len(components),
            "design_screenshot_base64": screenshot,
        }

    async def _execute_from_json(
        self, json_path: str, granularity: str, inputs: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        POC path: load pre-extracted design data from JSON file.

        Supports two modes:
        1. Pre-detected: JSON has `components[]` already classified by master
        2. Raw tree: JSON has `node_tree` that needs rule-based detection

        Expected JSON schema (design_export.json):
        {
            "file_key": "6kGd851qaAX4TiL44vpIrO",
            "page_name": "白色基础_照片直播",
            "page_node_id": "16650:538",
            "page_bounds": {"width": 393, "height": 852},
            "variables": {"color_name": "#hex", ...},
            "components": [
                {
                    "node_id": "16650:539",
                    "name": "Header",
                    "type": "organism",
                    "bounds": {"x": 0, "y": 0, "width": 393, "height": 92},
                    "children": ["StatusBar", "AppTitle", "BackButton"],
                    "screenshot_path": "screenshots/16650_539.png"
                }, ...
            ],
            "screenshots_dir": "data/design_export/screenshots/",
            "full_page_screenshot": "data/design_export/screenshots/full_page.png"
        }
        """
        # Resolve path relative to cwd if not absolute
        cwd = self.config.get("cwd") or inputs.get("cwd", ".")
        if not os.path.isabs(json_path):
            json_path = os.path.join(cwd, json_path)

        logger.info("DesignAnalyzerNode: loading from JSON %s", json_path)

        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        # --- Extract design tokens ---
        # Prefer structured design_tokens if present, otherwise parse from variables
        if data.get("design_tokens"):
            tokens = data["design_tokens"]
        else:
            tokens = self._parse_variables_to_tokens(data.get("variables", {}))

        # --- Get components (pre-detected or from raw tree) ---
        if "components" in data:
            # Mode 1: Pre-detected components from master's Figma extraction
            raw_components = self._normalize_predetected_components(data["components"])
            logger.info("DesignAnalyzerNode: loaded %d pre-detected components", len(raw_components))
        elif data.get("node_tree"):
            # Mode 2: Raw Figma node tree — run rule-based detection
            page_bounds = data.get("page_bounds", {})
            page_area = page_bounds.get("width", 1) * page_bounds.get("height", 1)
            raw_components = self._detect_components_from_tree(
                data["node_tree"], page_area, granularity
            )
            logger.info("DesignAnalyzerNode: detected %d components from tree", len(raw_components))
        else:
            raise ValueError("design_export.json must have 'components' or 'node_tree'")

        # --- Compute spatial adjacency ---
        components = self._compute_spatial_neighbors(raw_components)

        # --- Sort by implementation order ---
        components = self._sort_by_implementation_order(components)

        # --- Build skeleton structure ---
        page_bounds = data.get("page_bounds", {})
        skeleton = self._build_skeleton_from_components(components, page_bounds)

        # --- Screenshot paths ---
        screenshots_dir = data.get("screenshots_dir", "")
        full_page_screenshot = data.get("full_page_screenshot", "")

        # Initialize component registry
        logger.info(
            "DesignAnalyzerNode: %d components ready, %d tokens extracted",
            len(components), len(tokens),
        )

        return {
            "components": components,
            "tokens": tokens,
            "skeleton_structure": skeleton,
            "total_components": len(components),
            "design_screenshot_base64": full_page_screenshot,
            "screenshots_dir": screenshots_dir,
        }

    def _parse_variables_to_tokens(self, variables: Dict[str, str]) -> Dict[str, Any]:
        """
        Convert Figma design variables to structured design tokens.

        Input: {"Text Color/字体_黑60%": "#666666", "Brand-主题色/品牌色 (100%)": "#FFDD4C", ...}
        Output: {
            "colors": {"text-black-60": "#666666", "brand-primary": "#FFDD4C", ...},
            "fonts": {...},
            "spacing": {...},
            "border_radius": {...},
            "shadows": {...}
        }
        """
        tokens: Dict[str, Any] = {
            "colors": {},
            "fonts": {},
            "spacing": {},
            "border_radius": {},
            "shadows": {},
        }

        for var_name, value in variables.items():
            # Generate CSS-friendly variable name
            css_name = self._to_css_var_name(var_name)

            # Classify by Figma variable path prefix
            lower = var_name.lower()
            if any(k in lower for k in ["color", "fill", "brand", "text&icon"]):
                tokens["colors"][css_name] = value
            elif any(k in lower for k in ["font", "text-size", "typography"]):
                tokens["fonts"][css_name] = value
            elif any(k in lower for k in ["spacing", "gap", "padding", "margin"]):
                tokens["spacing"][css_name] = value
            elif any(k in lower for k in ["radius", "corner", "round"]):
                tokens["border_radius"][css_name] = value
            elif any(k in lower for k in ["shadow", "elevation"]):
                tokens["shadows"][css_name] = value
            else:
                # Default: treat hex values as colors, numbers as spacing
                if isinstance(value, str) and value.startswith("#"):
                    tokens["colors"][css_name] = value
                else:
                    tokens["colors"][css_name] = value

        return tokens

    @staticmethod
    def _to_css_var_name(figma_name: str) -> str:
        """
        Convert Figma variable name to CSS variable name.
        'Text Color/字体_黑60%' → 'text-color-60'
        'Brand-主题色/品牌色 (100%)' → 'brand-100'
        """
        import re
        name = figma_name.lower()
        # Replace path separators with dash
        name = re.sub(r'[/\\]', '-', name)
        name = re.sub(r'[_\s]+', '-', name)
        name = re.sub(r'[()%]+', '', name)
        # Remove non-ASCII characters (Chinese etc.)
        name = re.sub(r'[^\x00-\x7f]', '', name)
        # Clean up multiple dashes
        name = re.sub(r'-+', '-', name)
        name = name.strip('-')
        if len(name) < 3:
            logger.warning(
                "DesignAnalyzerNode: CSS var name '%s' too short after stripping "
                "non-ASCII from '%s' — consider providing design_tokens instead",
                name, figma_name,
            )
        return name

    def _normalize_predetected_components(
        self, components: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Normalize pre-detected components from master's JSON export.
        Ensures all required fields exist with correct types.

        Handles actual schema fields:
        - children_summary: [{name, node_id, type, bounds}]
        - text_content: ["text1", "text2"]
        - notes: "description"
        - neighbors: ["ComponentName"] (pre-computed)
        """
        normalized = []
        for comp in components:
            children_summary = comp.get("children_summary", [])
            children_names = [c.get("name", "") for c in children_summary] if children_summary else comp.get("children", [])

            normalized.append({
                "name": comp["name"],
                "node_id": comp.get("node_id", ""),
                "type": comp.get("type", "molecule"),
                "bounds": comp.get("bounds", {}),
                "neighbors": comp.get("neighbors", []),  # Use pre-computed if available
                "children_count": len(children_summary) if children_summary else len(comp.get("children", [])),
                "children_names": children_names,
                "children_summary": children_summary,
                "text_content": comp.get("text_content", []),
                "notes": comp.get("notes", ""),
                "is_reusable": False,
                "reuse_count": 0,
                "screenshot_path": comp.get("screenshot_path") or "",
            })
        return normalized

    def _detect_components_from_tree(
        self, node_tree: Dict, page_area: float, granularity: str
    ) -> List[Dict[str, Any]]:
        """
        Rule-based component detection from raw Figma node tree.

        Rules (from COMPONENT_DETECTION_PROMPT):
        1. Component Instances (type=INSTANCE) → always a component
        2. Visual boundary (fills/strokes/cornerRadius) → likely component
        3. children_count ≤ 2 → atom
        4. children_count 3-8 → molecule
        5. children_count > 8 → organism
        6. Area > 25% of page → section (folded into skeleton)
        7. Pure layout container (no visual styles) → not a component
        """
        components: List[Dict[str, Any]] = []
        self._walk_tree(node_tree, page_area, granularity, components, depth=0)
        return components

    def _walk_tree(
        self,
        node: Dict,
        page_area: float,
        granularity: str,
        results: List[Dict[str, Any]],
        depth: int,
    ) -> None:
        """Recursively walk Figma node tree and detect components."""
        node_type = node.get("type", "")
        children = node.get("children", [])

        # Skip non-visual nodes
        if node_type in ("DOCUMENT", "CANVAS", "PAGE"):
            for child in children:
                self._walk_tree(child, page_area, granularity, results, depth)
            return

        # Rule 1: Component instances are always components
        if node_type == "INSTANCE":
            results.append(self._node_to_component(node, page_area, force_type=None))
            return  # Don't recurse into instances

        # Only process FRAME and GROUP nodes as potential components
        if node_type not in ("FRAME", "GROUP", "COMPONENT", "COMPONENT_SET"):
            return

        bounds = _get_bounds(node)
        node_area = bounds.get("width", 0) * bounds.get("height", 0)
        area_ratio = node_area / page_area if page_area > 0 else 0
        children_count = len(children)
        has_visual_style = self._has_visual_boundary(node)

        # Rule 7: Pure layout container → skip (recurse into children)
        if not has_visual_style and node_type == "FRAME" and depth > 0:
            # Check if it's just a flex/grid wrapper with no visual decoration
            if granularity != "aggressive":
                for child in children:
                    self._walk_tree(child, page_area, granularity, results, depth + 1)
                return

        # Rule 6: Section (> 25% area) — treat as section, don't recurse
        if area_ratio > 0.25 and depth <= 1:
            results.append(self._node_to_component(node, page_area, force_type="section"))
            return

        # Determine component type by children count
        if has_visual_style or children_count >= 2 or node_type in ("COMPONENT", "COMPONENT_SET"):
            comp = self._node_to_component(node, page_area, force_type=None)
            results.append(comp)
            # Don't recurse — this node is a component boundary
            return

        # Conservative: recurse into children to find deeper components
        if granularity == "conservative" and children_count > 0:
            for child in children:
                self._walk_tree(child, page_area, granularity, results, depth + 1)
        elif children_count > 0:
            # Auto/aggressive: this frame itself is a component
            results.append(self._node_to_component(node, page_area, force_type=None))

    def _node_to_component(
        self, node: Dict, page_area: float, force_type: Optional[str]
    ) -> Dict[str, Any]:
        """Convert a Figma node to a component descriptor."""
        bounds = _get_bounds(node)
        children = node.get("children", [])
        children_count = len(children)

        if force_type:
            comp_type = force_type
        else:
            comp_type = self._classify_component_type(children_count, bounds, page_area)

        # Generate PascalCase name from Figma node name
        name = self._to_component_name(node.get("name", "Unknown"))

        return {
            "name": name,
            "node_id": node.get("id", ""),
            "type": comp_type,
            "bounds": bounds,
            "neighbors": [],
            "children_count": children_count,
            "children_names": [c.get("name", "") for c in children[:10]],
            "is_reusable": node.get("type") in ("COMPONENT", "COMPONENT_SET", "INSTANCE"),
            "reuse_count": 0,
            "screenshot_path": "",
        }

    @staticmethod
    def _classify_component_type(
        children_count: int, bounds: Dict, page_area: float
    ) -> str:
        """Classify component type based on children count and area ratio."""
        area = bounds.get("width", 0) * bounds.get("height", 0)
        area_ratio = area / page_area if page_area > 0 else 0

        if area_ratio > 0.25:
            return "section"
        if children_count <= 2:
            return "atom"
        if children_count <= 8:
            return "molecule"
        return "organism"

    @staticmethod
    def _has_visual_boundary(node: Dict) -> bool:
        """Check if a node has visual decoration (fills, strokes, cornerRadius, effects)."""
        if node.get("fills"):
            # Filter out invisible fills
            visible_fills = [f for f in node["fills"] if f.get("visible", True)]
            if visible_fills:
                return True
        if node.get("strokes"):
            visible_strokes = [s for s in node["strokes"] if s.get("visible", True)]
            if visible_strokes:
                return True
        if node.get("cornerRadius") and node["cornerRadius"] > 0:
            return True
        if node.get("effects"):
            visible_effects = [e for e in node["effects"] if e.get("visible", True)]
            if visible_effects:
                return True
        if node.get("backgroundColor"):
            return True
        return False

    @staticmethod
    def _to_component_name(figma_name: str) -> str:
        """Convert Figma node name to PascalCase component name."""
        import re
        # Remove special chars, keep alphanumeric and Chinese
        name = re.sub(r'[^\w\s-]', '', figma_name)
        # Split by separators
        parts = re.split(r'[\s_\-/]+', name)
        # PascalCase each part
        pascal = ''.join(p.capitalize() for p in parts if p)
        # Ensure starts with letter
        if pascal and not pascal[0].isalpha():
            pascal = 'C' + pascal
        return pascal or 'UnknownComponent'

    # ----- Private helpers (to be implemented) -----

    async def _fetch_design_tree(
        self, source: str, file_path: str, node_id: Optional[str]
    ) -> Dict[str, Any]:
        """Fetch design node tree via MCP."""
        # TODO: Implement MCP calls
        raise NotImplementedError("MCP integration pending")

    async def _extract_tokens(self, source: str, file_path: str) -> Dict[str, Any]:
        """Extract design tokens (colors, fonts, spacing) via MCP."""
        raise NotImplementedError("MCP integration pending")

    COMPONENT_DETECTION_PROMPT = """分析以下设计稿节点，判断它是否是一个独立的 UI 组件。

## 节点信息
名称: {node_name}
类型: {node_type}
尺寸: {width}x{height}
子节点数: {children_count}
子节点列表: {children_names}
布局: {layout}

## 判断规则
1. 有明确视觉边界（背景色/边框/圆角/阴影）→ 大概率是独立组件
2. 在设计稿中出现多次（相同结构）→ 可复用组件
3. 子节点数 ≤ 2 且无嵌套 → atom（按钮、图标、标签）
4. 子节点数 3-8 → molecule（卡片、输入框组、导航项）
5. 子节点数 > 8 或含多个 molecule → organism（侧边栏、表头、表单区域）
6. 占页面面积 > 25% → section（作为骨架的一部分，不单独拆出）
7. 纯布局容器（只有 flex/grid 没有视觉样式）→ 不是独立组件

## 输出格式（严格 JSON）
{{"is_component": true, "type": "atom|molecule|organism|section", "suggested_name": "PascalCase 组件名", "confidence": 0.0, "reason": "一句话判断理由"}}"""

    async def _detect_components(
        self, node_tree: Dict, granularity: str, inputs: Dict
    ) -> List[Dict[str, Any]]:
        """
        Use AI to classify nodes into components.

        Strategy:
        1. Mark all Component Instances as components (deterministic)
        2. For remaining frames, use heuristics:
           - children_count > 5 → candidate
           - has background/border/padding → visually independent
        3. For ambiguous nodes, ask Claude with COMPONENT_DETECTION_PROMPT
        4. Filter by confidence (< 0.6 → uncertain, pushed to HITL)
        5. section type nodes are folded into skeleton, not split as components
        """
        raise NotImplementedError("AI classification pending — MCP integration required")

    def _compute_spatial_neighbors(
        self, components: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Compute spatial adjacency based on bounding box proximity.

        If components already have pre-computed neighbors (from JSON export),
        those are preserved. Otherwise, computed from bounding box distance.

        Two components are neighbors if their bounding boxes are within 50px.
        """
        # Check if neighbors are already pre-computed (all components must have them)
        # If only some have neighbors, fall through to compute missing ones
        has_precomputed = all(comp.get("neighbors") for comp in components)
        if has_precomputed:
            logger.info("DesignAnalyzerNode: using pre-computed neighbors")
            return components

        # Compute from bounding box distance
        for i, comp_a in enumerate(components):
            neighbors = []
            a_bounds = comp_a.get("bounds", {})
            for j, comp_b in enumerate(components):
                if i == j:
                    continue
                b_bounds = comp_b.get("bounds", {})
                if self._are_spatially_adjacent(a_bounds, b_bounds):
                    neighbors.append(comp_b["name"])
            comp_a["neighbors"] = neighbors
        return components

    def _are_spatially_adjacent(
        self, a: Dict[str, float], b: Dict[str, float], threshold: float = 50.0
    ) -> bool:
        """Check if two bounding boxes are within threshold pixels of each other."""
        if not a or not b:
            return False
        a_right = a.get("x", 0) + a.get("width", 0)
        a_bottom = a.get("y", 0) + a.get("height", 0)
        b_right = b.get("x", 0) + b.get("width", 0)
        b_bottom = b.get("y", 0) + b.get("height", 0)

        h_gap = max(0, max(a.get("x", 0) - b_right, b.get("x", 0) - a_right))
        v_gap = max(0, max(a.get("y", 0) - b_bottom, b.get("y", 0) - a_bottom))

        return (h_gap + v_gap) <= threshold

    def _sort_by_implementation_order(
        self, components: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Sort components: atoms first, then molecules, then organisms, then sections.
        Within same type, reusable components first (they're dependencies).
        """
        type_priority = {"atom": 0, "molecule": 1, "organism": 2, "section": 3}
        return sorted(
            components,
            key=lambda c: (
                type_priority.get(c.get("type", "organism"), 2),
                -c.get("reuse_count", 0),  # Higher reuse = higher priority
                c.get("name", ""),
            ),
        )

    def _extract_skeleton(self, node_tree: Dict[str, Any]) -> Dict[str, Any]:
        """Extract top-level layout structure from Figma node tree."""
        bounds = _get_bounds(node_tree)
        layout_mode = node_tree.get("layoutMode", "VERTICAL")
        children = node_tree.get("children", [])

        sections = []
        for child in children:
            child_bounds = _get_bounds(child)
            sections.append({
                "name": child.get("name", ""),
                "node_id": child.get("id", ""),
                "layout": child.get("layoutMode", "NONE"),
                "bounds": child_bounds,
            })

        return {
            "layout": "horizontal" if layout_mode == "HORIZONTAL" else "vertical",
            "width": bounds.get("width", 0),
            "height": bounds.get("height", 0),
            "sections": sections,
        }

    def _build_skeleton_from_components(
        self, components: List[Dict[str, Any]], page_bounds: Dict
    ) -> Dict[str, Any]:
        """Build skeleton structure from detected components (for JSON mode)."""
        sections = []
        for comp in components:
            sections.append({
                "name": comp["name"],
                "node_id": comp.get("node_id", ""),
                "type": comp.get("type", "molecule"),
                "bounds": comp.get("bounds", {}),
            })

        return {
            "layout": "vertical",
            "width": page_bounds.get("width", 0),
            "height": page_bounds.get("height", 0),
            "sections": sections,
        }

    async def _get_design_screenshot(
        self, source: str, file_path: str, node_id: Optional[str]
    ) -> str:
        """Get full-page design screenshot as base64 for final comparison."""
        # TODO: MCP get_screenshot or Figma export
        return ""

    def _render_config(self, key: str, inputs: Dict[str, Any]) -> str:
        """Render template variables in config value."""
        value = self.config.get(key, "")
        if not isinstance(value, str):
            return value
        # Simple {key} replacement
        for k, v in inputs.items():
            if isinstance(v, str):
                value = value.replace(f"{{{k}}}", v)
        return value
