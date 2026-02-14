"""
Design-to-Code Pipeline Nodes

Three new node types for the Design-to-Code workflow:
1. DesignAnalyzerNode - Analyzes design files, extracts component tree + tokens
2. SkeletonGeneratorNode - Generates page layout skeleton
3. VisualDiffNode - Compares design screenshots with implementation screenshots

State extension:
- ComponentRegistry: tracks generated components across loop iterations
"""

import asyncio
import json
import logging
import os
import re
from typing import Any, Dict, List, Optional, Tuple

from .registry import BaseNodeImpl, register_node_type

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Default prompts — thin layer: describe WHAT, not HOW
# ---------------------------------------------------------------------------

DEFAULT_SKELETON_PROMPT = """You are building a page layout skeleton for a mobile app screen.

## Page Dimensions
{page_width}px × {page_height}px

## Component Sections (top to bottom)
{skeleton_structure}

## Design Tokens
{tokens}

## Target Framework
{framework}

## Task
Create a single `PageSkeleton.tsx` file that:
1. Defines the overall page container matching the exact dimensions
2. Places a slot `<div data-component="ComponentName">` for each component section at its correct position
3. Uses Tailwind CSS for layout (flex/grid)
4. Defines CSS custom properties from the design tokens at the root level
5. Exports a `COMPONENT_SLOTS` array listing all component names

Each slot div should have width/height matching the component's bounds from the section list above.

Output ONLY the complete TSX code, no explanation."""

DEFAULT_COMPONENT_PROMPT = """You are restoring a single UI component from a design specification.

## Component
Name: {component_name}
Type: {component_type}
Dimensions: {bounds_width}px × {bounds_height}px
Figma Node: {node_id}

## Visual Description
{notes}

## Text Content (exact strings from design)
{text_content}

## Child Elements
{children_summary}

## Design Tokens (use these instead of hardcoded values)
{tokens}

## Page Skeleton (for layout context)
{skeleton}

## Already Completed Components (interface reference)
{interface_summary}

## Spatial Neighbor Code (for visual alignment)
{neighbor_code}

## Design Screenshot
{screenshot_instruction}

## Constraints
- React + TypeScript + Tailwind CSS
- Export a named function component with Props interface
- Match colors, font sizes, spacing, and border radius from design tokens
- Use the exact text strings listed above
- Images/icons: use placeholder SVGs or colored divs matching dimensions
- Component must render independently (no external state dependencies)
- Visual fidelity only — no interaction logic needed
- If a design screenshot is provided above, ensure your implementation matches it visually

Output ONLY the complete TSX file content, no explanation.
At the end, add a comment block with the component signature:
// SIGNATURE: export {component_name}, props: {{...}}, css-vars: [...]"""

DEFAULT_ASSEMBLER_PROMPT = """You are assembling independently generated UI components into a complete page.

## Page Skeleton
{skeleton_code}

## Generated Components
{component_code}

## Design Tokens
{tokens}

## Component Interface Summary
{interface_summary}

## Task
1. Replace each `data-component="X"` placeholder in the skeleton with the actual `<X />` component
2. Add all necessary import statements (relative paths: `./components/X`)
3. Ensure design token CSS variables are defined at the page root
4. Check that spacing between components is consistent with the skeleton layout
5. The result must pass TypeScript compilation and render correctly

Output ONLY the complete `Page.tsx` file code, no explanation."""


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
# Code extraction utilities
# ---------------------------------------------------------------------------


def _extract_code_block(text: str) -> str:
    """Extract the first tsx/ts code block from LLM output, or return raw text."""
    pattern = r"```(?:tsx|typescript|jsx|ts|js)?\s*\n(.*?)```"
    match = re.search(pattern, text, re.DOTALL)
    if match:
        return match.group(1).strip()
    return text.strip()


def _extract_props_interface(code: str) -> str:
    """Extract TypeScript Props interface from generated component code.

    Looks for patterns like:
      interface HeaderProps { ... }
      type HeaderProps = { ... }
    Returns the full interface/type definition string, or empty string.
    """
    raw = _extract_code_block(code) if "```" in code else code

    # Match `interface XProps { ... }`
    match = re.search(
        r"((?:export\s+)?interface\s+\w+Props\s*\{[^}]*\})",
        raw,
        re.DOTALL,
    )
    if match:
        return match.group(1).strip()

    # Match `type XProps = { ... }`
    match = re.search(
        r"((?:export\s+)?type\s+\w+Props\s*=\s*\{[^}]*\})",
        raw,
        re.DOTALL,
    )
    if match:
        return match.group(1).strip()

    return ""


def _extract_css_variables(code: str) -> List[str]:
    """Extract CSS variable references (var(--xxx)) from generated code.
    Handles fallback values like var(--color-border, #eee).
    """
    raw = _extract_code_block(code) if "```" in code else code
    matches = re.findall(r"var\((--[\w-]+)", raw)
    return sorted(set(matches))


# ---------------------------------------------------------------------------
# Shared: ComponentRegistry state helpers
# ---------------------------------------------------------------------------

def empty_component_registry() -> Dict[str, Any]:
    """Initial state for component registry. Injected into workflow state at start."""
    return {
        "components": [],       # List of ComponentEntry dicts
        "tokens": {},           # Design tokens (colors, fonts, spacing)
        "skeleton_code": "",    # Generated skeleton code
        "total": 0,
        "completed": 0,
        "failed": 0,
    }


def add_component_to_registry(
    registry: Dict[str, Any],
    component: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Add a completed component to the registry.

    component shape:
    {
        "name": str,            # e.g. "LoginButton"
        "file_path": str,       # e.g. "components/LoginButton.tsx"
        "export_name": str,     # e.g. "LoginButton"
        "props_interface": str, # e.g. "interface LoginButtonProps { variant: string }"
        "css_variables": list,  # e.g. ["--btn-primary", "--btn-radius"]
        "node_id": str,         # Original design node reference
        "status": str,          # "completed" | "failed" | "pending"
        "code": str,            # Full component source code
        "neighbors": list,      # Spatial neighbor component names
    }
    """
    updated = {**registry}
    updated["components"] = [*registry["components"], component]
    updated["total"] = len(updated["components"])
    updated["completed"] = sum(
        1 for c in updated["components"] if c.get("status") == "completed"
    )
    updated["failed"] = sum(
        1 for c in updated["components"] if c.get("status") == "failed"
    )
    return updated


def get_neighbor_code(
    registry: Dict[str, Any],
    current_component_name: str,
    neighbor_names: List[str],
) -> str:
    """
    Get full code of spatial neighbors for context passing.
    Returns concatenated code of completed neighbor components.
    """
    parts = []
    for comp in registry.get("components", []):
        if (
            comp["name"] in neighbor_names
            and comp["name"] != current_component_name
            and comp.get("status") == "completed"
        ):
            parts.append(f"// --- {comp['name']} ({comp['file_path']}) ---\n{comp['code']}")
    return "\n\n".join(parts)


def get_interface_summary(registry: Dict[str, Any]) -> str:
    """
    Get lightweight interface summary of all completed components.
    ~10-15 lines per component, suitable for context budget.
    """
    lines = []
    for comp in registry.get("components", []):
        if comp.get("status") == "completed":
            lines.append(
                f"// {comp['file_path']}\n"
                f"export {{ {comp['export_name']} }};\n"
                f"{comp.get('props_interface', '')}\n"
                f"// CSS vars: {', '.join(comp.get('css_variables', []))}\n"
            )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Node 1: DesignAnalyzerNode
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

        registry = empty_component_registry()
        registry["tokens"] = tokens

        return {
            "components": components,
            "tokens": tokens,
            "skeleton_structure": self._extract_skeleton(node_tree),
            "total_components": len(components),
            "design_screenshot_base64": screenshot,
            "component_registry": registry,
            "component_list": components,
            "current_component_index": 0,
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
        registry = empty_component_registry()
        registry["tokens"] = tokens

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
            "component_registry": registry,
            "component_list": components,
            "current_component_index": 0,
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


# ---------------------------------------------------------------------------
# Node 2: SkeletonGeneratorNode
# ---------------------------------------------------------------------------

@register_node_type(
    node_type="skeleton_generator",
    display_name="Skeleton Generator",
    description="Generates page layout skeleton (grid/flex structure) without component details",
    category="processing",
    input_schema={
        "type": "object",
        "properties": {
            "prompt_template": {
                "type": "string",
                "description": "Prompt template for skeleton generation. Use {skeleton_structure} and {tokens} placeholders.",
            },
            "output_dir": {
                "type": "string",
                "description": "Directory to write skeleton files",
            },
            "framework": {
                "type": "string",
                "description": "Target framework",
                "enum": ["react-tailwind", "react-css-modules", "vue-tailwind"],
            },
            "cwd": {
                "type": "string",
                "description": "Working directory for Claude CLI",
            },
            "timeout": {
                "type": "number",
                "description": "Execution timeout in seconds",
            },
        },
        "required": ["prompt_template", "cwd"],
    },
    output_schema={
        "type": "object",
        "properties": {
            "skeleton_code": {"type": "string"},
            "files_created": {"type": "array", "items": {"type": "string"}},
            "success": {"type": "boolean"},
        },
    },
    icon="layout",
    color="#06B6D4",
)
class SkeletonGeneratorNode(BaseNodeImpl):
    """
    Generates the page-level layout skeleton.
    Uses Claude CLI to create flex/grid container structure.
    Does NOT fill in component details — only layout placeholders.

    Input context:
    - skeleton_structure from DesignAnalyzerNode
    - tokens from DesignAnalyzerNode

    Output:
    - skeleton_code: the generated layout code
    - Promotes skeleton_code to component_registry for downstream use
    """

    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        from .agents import stream_claude_events, _make_sse_event_callback

        skeleton_structure = inputs.get("skeleton_structure", {})
        tokens = inputs.get("tokens", {})
        prompt_template = self.config.get("prompt_template", "") or DEFAULT_SKELETON_PROMPT
        cwd = self.config.get("cwd", ".")
        timeout = self.config.get("timeout", 300)
        framework = self.config.get("framework", "react-tailwind")

        # Build readable section list for prompt
        sections = skeleton_structure.get("sections", [])
        section_lines = []
        for s in sections:
            b = s.get("bounds", {})
            section_lines.append(
                f"- {s.get('name', 'Unknown')} ({s.get('type', 'component')}): "
                f"x={b.get('x', 0)}, y={b.get('y', 0)}, "
                f"{b.get('width', 0)}×{b.get('height', 0)}px"
            )
        sections_text = "\n".join(section_lines) if section_lines else json.dumps(skeleton_structure, indent=2)

        # Render prompt with design data
        prompt = prompt_template.replace("{skeleton_structure}", sections_text)
        prompt = prompt.replace("{tokens}", json.dumps(tokens, indent=2))
        prompt = prompt.replace("{framework}", framework)
        prompt = prompt.replace("{page_width}", str(skeleton_structure.get("width", 393)))
        prompt = prompt.replace("{page_height}", str(skeleton_structure.get("height", 852)))

        logger.info("SkeletonGeneratorNode [%s]: generating skeleton", self.node_id)

        # Call Claude CLI
        on_event = _make_sse_event_callback(inputs, self.node_id)
        result = await stream_claude_events(
            prompt=prompt,
            cwd=cwd,
            on_event=on_event,
            timeout=timeout,
        )

        # stream_claude_events returns str (result text) or dict in test mocks
        skeleton_code = result.get("result", "") if isinstance(result, dict) else result

        # Update component registry with skeleton
        registry = inputs.get("component_registry", empty_component_registry())
        registry = {**registry, "skeleton_code": skeleton_code}

        return {
            "skeleton_code": skeleton_code,
            "files_created": ["layout/PageSkeleton.tsx"] if skeleton_code else [],
            "success": bool(skeleton_code),
            "component_registry": registry,
        }


# ---------------------------------------------------------------------------
# Node 3 (part of loop): ComponentGeneratorNode
# ---------------------------------------------------------------------------

@register_node_type(
    node_type="component_generator",
    display_name="Component Generator",
    description="Generates code for a single UI component based on design data + context",
    category="agent",
    input_schema={
        "type": "object",
        "properties": {
            "prompt_template": {
                "type": "string",
                "description": "Code generation prompt. Placeholders: {component_name}, {design_data}, {tokens}, {skeleton}, {interface_summary}, {neighbor_code}",
            },
            "cwd": {
                "type": "string",
                "description": "Working directory for Claude CLI",
            },
            "timeout": {
                "type": "number",
                "description": "Timeout per component in seconds",
            },
            "framework": {
                "type": "string",
                "enum": ["react-tailwind", "react-css-modules", "vue-tailwind"],
            },
        },
        "required": ["prompt_template", "cwd"],
    },
    output_schema={
        "type": "object",
        "properties": {
            "code": {"type": "string"},
            "file_path": {"type": "string"},
            "export_name": {"type": "string"},
            "props_interface": {"type": "string"},
            "success": {"type": "boolean"},
        },
    },
    icon="code",
    color="#10B981",
)
class ComponentGeneratorNode(BaseNodeImpl):
    """
    Generates code for a single component within the loop.

    Context budget (~1.2K tokens):
    1. Design tokens + skeleton (~500 tokens) - global, fixed
    2. Interface summary of completed components (~200 tokens) - grows slowly
    3. Spatial neighbor full code (~500 tokens) - dynamic, 1-3 neighbors

    Uses current_component_index from state to pick which component to generate.
    """

    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        from .agents import stream_claude_events, _make_sse_event_callback

        # Get current component from list
        component_list = inputs.get("component_list", [])
        current_index = inputs.get("current_component_index", 0)

        if current_index >= len(component_list):
            return {"success": False, "code": "", "message": "No more components"}

        current_component = component_list[current_index]
        registry = inputs.get("component_registry", empty_component_registry())

        # Build three-layer context
        tokens_json = json.dumps(registry.get("tokens", {}), indent=2)
        skeleton = registry.get("skeleton_code", "")
        interface_summary = get_interface_summary(registry)
        neighbor_code = get_neighbor_code(
            registry,
            current_component["name"],
            current_component.get("neighbors", []),
        )

        # Build rich component context from design data
        bounds = current_component.get("bounds", {})
        text_content = current_component.get("text_content", [])
        text_content_str = "\n".join(f'- "{t}"' for t in text_content) if text_content else "(none)"
        children_summary = current_component.get("children_summary", [])
        if children_summary:
            children_lines = []
            for child in children_summary:
                cb = child.get("bounds", {})
                children_lines.append(
                    f"- {child.get('name', '?')} ({child.get('type', 'element')}): "
                    f"{cb.get('width', 0)}×{cb.get('height', 0)}px"
                )
            children_str = "\n".join(children_lines)
        else:
            children_names = current_component.get("children_names", [])
            children_str = "\n".join(f"- {n}" for n in children_names) if children_names else "(none)"
        notes = current_component.get("notes", "") or "(no visual description available)"

        # Build screenshot instruction (conditional on screenshot_path existence)
        cwd = self.config.get("cwd", ".")
        screenshot_path = current_component.get("screenshot_path", "")
        if screenshot_path:
            abs_screenshot = os.path.join(cwd, screenshot_path) if not os.path.isabs(screenshot_path) else screenshot_path
            if os.path.isfile(abs_screenshot):
                screenshot_instruction = (
                    f"请先用 Read 工具读取 {abs_screenshot} 查看此组件的设计稿截图，"
                    f"确保你的实现与设计视觉一致。截图展示了组件的真实外观，"
                    f"包括精确的颜色、间距、字体大小和布局。"
                )
                logger.info(
                    "ComponentGeneratorNode [%s]: screenshot available at %s",
                    self.node_id, abs_screenshot,
                )
            else:
                screenshot_instruction = "(设计截图文件不存在，请依据上方文字描述还原组件)"
                logger.warning(
                    "ComponentGeneratorNode [%s]: screenshot_path set but file missing: %s",
                    self.node_id, abs_screenshot,
                )
        else:
            screenshot_instruction = "(无设计截图，请依据上方文字描述还原组件)"

        # Render prompt
        prompt = self.config.get("prompt_template", "") or DEFAULT_COMPONENT_PROMPT
        prompt = prompt.replace("{component_name}", current_component["name"])
        prompt = prompt.replace("{component_type}", current_component.get("type", "molecule"))
        prompt = prompt.replace("{node_id}", current_component.get("node_id", ""))
        prompt = prompt.replace("{bounds_width}", str(bounds.get("width", 0)))
        prompt = prompt.replace("{bounds_height}", str(bounds.get("height", 0)))
        prompt = prompt.replace("{notes}", notes)
        prompt = prompt.replace("{text_content}", text_content_str)
        prompt = prompt.replace("{children_summary}", children_str)
        prompt = prompt.replace("{tokens}", tokens_json)
        prompt = prompt.replace("{skeleton}", skeleton)
        prompt = prompt.replace("{interface_summary}", interface_summary)
        prompt = prompt.replace("{neighbor_code}", neighbor_code)
        prompt = prompt.replace("{screenshot_instruction}", screenshot_instruction)
        prompt = prompt.replace("{framework}", self.config.get("framework", "react-tailwind"))

        timeout = self.config.get("timeout", 300)

        logger.info(
            "ComponentGeneratorNode [%s]: generating %s (%d/%d)",
            self.node_id, current_component["name"],
            current_index + 1, len(component_list),
        )

        # Call Claude CLI
        on_event = _make_sse_event_callback(inputs, self.node_id)
        result = await stream_claude_events(
            prompt=prompt,
            cwd=cwd,
            on_event=on_event,
            timeout=timeout,
        )

        # stream_claude_events returns str (result text) or dict in test mocks
        if isinstance(result, dict):
            code = result.get("result", "")
            success = bool(code) and result.get("exit_code", 1) == 0
        else:
            code = result
            success = bool(code) and not code.startswith("[Error]")

        return {
            "code": code,
            "file_path": f"components/{current_component['name']}.tsx",
            "export_name": current_component["name"],
            "props_interface": _extract_props_interface(code),
            "css_variables": _extract_css_variables(code),
            "success": success,
            "component_name": current_component["name"],
            "component_index": current_index,
        }


# ---------------------------------------------------------------------------
# Node 4 (validation): VisualDiffNode
# ---------------------------------------------------------------------------

@register_node_type(
    node_type="visual_diff",
    display_name="Visual Diff",
    description="Compares design screenshot with implementation screenshot using multi-layer validation",
    category="validation",
    input_schema={
        "type": "object",
        "properties": {
            "validation_level": {
                "type": "string",
                "description": "Validation depth: 'L1' (compile only), 'L1L2' (compile + pixel), 'full' (compile + pixel + AI)",
                "enum": ["L1", "L1L2", "full"],
            },
            "pixel_threshold": {
                "type": "number",
                "description": "Pixel diff threshold percentage for auto-pass (default 5.0)",
            },
            "ai_threshold": {
                "type": "number",
                "description": "Pixel diff percentage above which AI review is triggered (default 15.0)",
            },
            "design_source": {
                "type": "string",
                "enum": ["figma", "pencil"],
            },
            "design_file": {
                "type": "string",
                "description": "Design file path/URL for screenshot extraction",
            },
            "dev_server_url": {
                "type": "string",
                "description": "Local dev server URL for Playwright screenshot",
            },
            "component_selector": {
                "type": "string",
                "description": "CSS selector template for component screenshot. Use {component_name} placeholder.",
            },
            "cwd": {
                "type": "string",
                "description": "Working directory",
            },
        },
        "required": ["design_source", "design_file"],
    },
    output_schema={
        "type": "object",
        "properties": {
            "verified": {"type": "boolean"},
            "validation_layers": {
                "type": "object",
                "properties": {
                    "L1_compile": {"type": "object"},
                    "L2_pixel": {"type": "object"},
                    "L3_ai_visual": {"type": "object"},
                },
            },
            "pixel_diff_percent": {"type": "number"},
            "ai_verdict": {"type": "string"},
            "diff_details": {"type": "array"},
            "message": {"type": "string"},
        },
    },
    icon="eye",
    color="#F59E0B",
)
class VisualDiffNode(BaseNodeImpl):
    """
    Multi-layer visual validation node.

    Validation layers:
    - L1 (compile): TypeScript build check — free, 100% for syntax errors
    - L2 (pixel): Playwright screenshot + pixelmatch — fast, catches layout errors
    - L3 (AI visual): Claude Vision comparison — semantic, catches subtle issues

    Smoke test strategy (from team discussion):
    - Components 1-3: full (L1+L2+L3) — calibrate baseline
    - Components 4+: L1L2 — save cost
    - Full page: full (L1+L2+L3+L4 human optional)

    Threshold cascade:
    - pixel_diff < 5%: auto-pass
    - pixel_diff 5-15%: trigger L3 AI review
    - pixel_diff > 15%: auto-fail, trigger retry
    """

    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        validation_level = self.config.get("validation_level", "L1L2")
        pixel_threshold = self.config.get("pixel_threshold", 5.0)
        ai_threshold = self.config.get("ai_threshold", 15.0)
        cwd = self.config.get("cwd") or inputs.get("cwd", ".")

        component_name = inputs.get("component_name", "")
        component_index = inputs.get("component_index", 0)

        # Resolve design screenshot path for this component
        design_screenshot = ""
        component_list = inputs.get("component_list", [])
        screenshots_dir = inputs.get("screenshots_dir", "")
        if component_index < len(component_list):
            comp = component_list[component_index]
            design_screenshot = comp.get("screenshot_path", "")
            if design_screenshot and screenshots_dir and not os.path.isabs(design_screenshot):
                design_screenshot = os.path.join(cwd, design_screenshot)

        logger.info(
            "VisualDiffNode [%s]: validating %s (level=%s)",
            self.node_id, component_name, validation_level,
        )

        result = {
            "verified": False,
            "validation_layers": {},
            "pixel_diff_percent": 0.0,
            "ai_verdict": "",
            "diff_details": [],
            "message": "",
        }

        # --- L1: Compile check ---
        l1_result = await self._run_compile_check(inputs)
        result["validation_layers"]["L1_compile"] = l1_result

        if not l1_result["passed"]:
            result["message"] = f"L1 compile failed: {l1_result.get('error', '')}"
            return result

        if validation_level == "L1":
            result["verified"] = True
            result["message"] = "L1 compile passed"
            return result

        # --- L2: Pixel diff ---
        # actual_screenshot would be captured by Playwright from dev server
        actual_screenshot = inputs.get("actual_screenshot", "")
        output_dir = os.path.join(cwd, "visual-diff-output")
        l2_result = await self._run_pixel_diff(
            design_screenshot=design_screenshot,
            actual_screenshot=actual_screenshot,
            component_id=component_name,
            output_dir=output_dir,
        )
        result["validation_layers"]["L2_pixel"] = l2_result
        result["pixel_diff_percent"] = l2_result.get("diff_percent", 100.0)

        if l2_result["diff_percent"] < pixel_threshold:
            result["verified"] = True
            result["message"] = f"L2 pixel diff {l2_result['diff_percent']:.1f}% < {pixel_threshold}% threshold — auto-pass"
            return result

        if l2_result["diff_percent"] > ai_threshold:
            result["verified"] = False
            result["message"] = f"L2 pixel diff {l2_result['diff_percent']:.1f}% > {ai_threshold}% — auto-fail, retry recommended"
            return result

        if validation_level == "L1L2":
            # In L1L2 mode, pass if within reasonable range
            result["verified"] = l2_result["diff_percent"] < ai_threshold
            result["message"] = f"L2 pixel diff {l2_result['diff_percent']:.1f}% (L3 skipped in L1L2 mode)"
            return result

        # --- L3: AI visual comparison ---
        l3_result = await self._run_ai_visual_comparison(
            self.node_id, component_name, inputs
        )
        result["validation_layers"]["L3_ai_visual"] = l3_result
        result["ai_verdict"] = l3_result.get("verdict", "unknown")
        result["diff_details"] = l3_result.get("differences", [])

        result["verified"] = l3_result.get("verdict") in ("pass", "acceptable")
        result["message"] = (
            f"L3 AI verdict: {l3_result.get('verdict', 'unknown')} — "
            f"{l3_result.get('summary', '')}"
        )

        return result

    # ----- Validation layer implementations -----

    async def _run_compile_check(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """L1: Run TypeScript build to check syntax."""
        cwd = self.config.get("cwd", ".")
        try:
            proc = await asyncio.create_subprocess_shell(
                "npx tsc --noEmit 2>&1 | tail -20",
                cwd=cwd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=60)
            output = stdout.decode() if stdout else ""
            passed = proc.returncode == 0
            return {"passed": passed, "output": output[:500], "error": "" if passed else output[:200]}
        except asyncio.TimeoutError:
            return {"passed": False, "output": "", "error": "Compile check timed out"}
        except Exception as e:
            return {"passed": False, "output": "", "error": str(e)}

    async def _run_pixel_diff(
        self,
        design_screenshot: str,
        actual_screenshot: str,
        component_id: str,
        output_dir: str,
    ) -> Dict[str, Any]:
        """
        L2: Pixel diff via visual-comparator.ts CLI subprocess.

        Args:
            design_screenshot: Path to design screenshot PNG
            actual_screenshot: Path to actual implementation screenshot PNG
            component_id: Component identifier for output naming
            output_dir: Directory for diff output files

        Returns:
            CLI stdout JSON: {component_id, verdict, pixel_diff, timestamp}

        Implemented by browser-tester (T116).
        """
        import json as _json
        import os

        if not os.path.isfile(design_screenshot):
            return {
                "diff_percent": 100.0,
                "component_id": component_id,
                "verdict": "error",
                "error": f"Design screenshot not found: {design_screenshot}",
            }
        if not os.path.isfile(actual_screenshot):
            return {
                "diff_percent": 100.0,
                "component_id": component_id,
                "verdict": "error",
                "error": f"Actual screenshot not found: {actual_screenshot}",
            }

        os.makedirs(output_dir, exist_ok=True)

        cwd = self.config.get("frontend_cwd", None)
        if not cwd:
            cwd = os.path.abspath(
                os.path.join(os.path.dirname(__file__), "..", "..", "..", "frontend")
            )

        cmd = (
            f"npx tsx tests/visual-diff/visual-comparator.ts compare"
            f' --design "{os.path.abspath(design_screenshot)}"'
            f' --actual "{os.path.abspath(actual_screenshot)}"'
            f' --output "{os.path.abspath(output_dir)}"'
            f' --component-id "{component_id}"'
        )

        try:
            proc = await asyncio.create_subprocess_shell(
                cmd,
                cwd=cwd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=60
            )

            if proc.returncode != 0:
                err_msg = stderr.decode().strip() if stderr else "unknown error"
                return {
                    "diff_percent": 100.0,
                    "component_id": component_id,
                    "verdict": "error",
                    "error": f"CLI exit code {proc.returncode}: {err_msg[:300]}",
                }

            cli_output = _json.loads(stdout.decode().strip())
            pixel_diff = cli_output.get("pixel_diff", {})
            return {
                "diff_percent": pixel_diff.get("diffPercentage", 100.0) if isinstance(pixel_diff, dict) else 100.0,
                "component_id": cli_output.get("component_id", component_id),
                "verdict": cli_output.get("verdict", "unknown"),
                "timestamp": cli_output.get("timestamp", ""),
                "diff_image": os.path.join(output_dir, "diff.png"),
            }

        except asyncio.TimeoutError:
            return {
                "diff_percent": 100.0,
                "component_id": component_id,
                "verdict": "error",
                "error": "Pixel diff timed out after 60s",
            }
        except _json.JSONDecodeError as exc:
            raw = stdout.decode()[:200] if stdout else ""
            return {
                "diff_percent": 100.0,
                "component_id": component_id,
                "verdict": "error",
                "error": f"Failed to parse CLI JSON: {exc}. Raw: {raw}",
            }
        except Exception as exc:
            return {
                "diff_percent": 100.0,
                "component_id": component_id,
                "verdict": "error",
                "error": f"Pixel diff failed: {exc}",
            }

    async def _run_ai_visual_comparison(
        self, design_node_id: str, component_name: str, inputs: Dict[str, Any]
    ) -> Dict[str, Any]:
        """L3: Claude Vision semantic comparison."""
        # TODO: Implement
        # 1. Get both screenshots
        # 2. Send to Claude with comparison prompt
        # 3. Parse structured verdict
        return {
            "verdict": "unknown",
            "summary": "Not implemented",
            "differences": [],
            "confidence": 0.0,
        }


# ---------------------------------------------------------------------------
# Node 5: AssemblerNode
# ---------------------------------------------------------------------------

@register_node_type(
    node_type="assembler",
    display_name="Component Assembler",
    description="Assembles generated components into a complete page with proper imports and layout",
    category="processing",
    input_schema={
        "type": "object",
        "properties": {
            "prompt_template": {
                "type": "string",
                "description": "Assembly prompt. Placeholders: {skeleton_code}, {component_registry}, {tokens}",
            },
            "cwd": {
                "type": "string",
                "description": "Working directory",
            },
            "timeout": {
                "type": "number",
                "description": "Timeout in seconds",
            },
        },
        "required": ["prompt_template", "cwd"],
    },
    output_schema={
        "type": "object",
        "properties": {
            "assembled_code": {"type": "string"},
            "files_modified": {"type": "array", "items": {"type": "string"}},
            "success": {"type": "boolean"},
            "build_passed": {"type": "boolean"},
        },
    },
    icon="puzzle",
    color="#EC4899",
)
class AssemblerNode(BaseNodeImpl):
    """
    Assembles all generated components into a complete, buildable page.

    This is NOT simple concatenation — it's an AI-driven integration step:
    - Resolves import paths
    - Handles CSS/Tailwind class deduplication
    - Wires component props
    - Ensures layout matches skeleton structure
    - Runs build verification after assembly
    """

    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        from .agents import stream_claude_events, _make_sse_event_callback

        registry = inputs.get("component_registry", empty_component_registry())
        prompt_template = self.config.get("prompt_template", "") or DEFAULT_ASSEMBLER_PROMPT
        cwd = self.config.get("cwd", ".")
        timeout = self.config.get("timeout", 600)

        # Build assembly context
        all_component_code = "\n\n".join(
            f"// --- {c['name']} ({c['file_path']}) ---\n{c['code']}"
            for c in registry.get("components", [])
            if c.get("status") == "completed"
        )

        prompt = prompt_template.replace("{skeleton_code}", registry.get("skeleton_code", ""))
        prompt = prompt.replace("{component_code}", all_component_code)
        prompt = prompt.replace("{tokens}", json.dumps(registry.get("tokens", {}), indent=2))
        prompt = prompt.replace("{interface_summary}", get_interface_summary(registry))

        logger.info(
            "AssemblerNode [%s]: assembling %d components",
            self.node_id, registry.get("completed", 0),
        )

        on_event = _make_sse_event_callback(inputs, self.node_id)
        result = await stream_claude_events(
            prompt=prompt,
            cwd=cwd,
            on_event=on_event,
            timeout=timeout,
        )

        # stream_claude_events returns str (result text) or dict in test mocks
        assembled_code = result.get("result", "") if isinstance(result, dict) else result
        success = bool(assembled_code) and not (isinstance(assembled_code, str) and assembled_code.startswith("[Error]"))

        # Run build check
        build_passed = False
        if success:
            build_result = await self._run_build(cwd)
            build_passed = build_result["passed"]

        return {
            "assembled_code": assembled_code,
            "files_modified": ["Page.tsx"] if success else [],
            "success": success,
            "build_passed": build_passed,
        }

    async def _run_build(self, cwd: str) -> Dict[str, Any]:
        """Run build to verify assembled code compiles."""
        try:
            proc = await asyncio.create_subprocess_shell(
                "npx next build 2>&1 | tail -30",
                cwd=cwd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=120)
            return {"passed": proc.returncode == 0, "output": stdout.decode()[:500] if stdout else ""}
        except Exception as e:
            return {"passed": False, "output": str(e)}
