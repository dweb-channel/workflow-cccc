"""Node 3: SpecAssemblerNode — assembles final design_spec.json.

Wraps page metadata, design tokens, source info, orders components
by z_index, validates auto-layout compliance, and writes output.
"""

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List

from .registry import BaseNodeImpl, register_node_type

logger = logging.getLogger(__name__)


@register_node_type(
    node_type="spec_assembler",
    display_name="Spec Assembler",
    description=(
        "Assembles final design_spec.json from completed ComponentSpecs. "
        "Wraps page metadata, design tokens, source info, and orders "
        "components by z_index."
    ),
    category="output",
    input_schema={
        "type": "object",
        "properties": {
            "components": {
                "type": "array",
                "description": "List of completed ComponentSpec dicts",
            },
            "page": {"type": "object"},
            "design_tokens": {"type": "object"},
            "source": {"type": "object"},
            "output_dir": {"type": "string"},
        },
    },
    output_schema={
        "type": "object",
        "properties": {
            "spec_path": {"type": "string"},
            "spec_document": {"type": "object"},
        },
    },
    icon="file-json",
    color="#10B981",
)
class SpecAssemblerNode(BaseNodeImpl):
    """Node 3: Assembles final design_spec.json.

    1. Wraps page metadata, design_tokens, source info
    2. Orders components by z_index (bottom layer first)
    3. Validates auto-layout compliance
    4. Writes to {output_dir}/design_spec.json
    """

    @staticmethod
    def _collect_inferred_nodes(
        node: Dict[str, Any], results: List[Dict[str, Any]],
    ) -> None:
        """Recursively collect nodes with layoutSource == 'inferred'.

        Only flags nodes with >= 2 children, since single/zero-child
        containers don't benefit from auto-layout (no gap to compute).
        """
        children = node.get("children", [])
        if node.get("layoutSource") == "inferred" and len(children) >= 2:
            results.append({
                "id": node.get("id", ""),
                "name": node.get("name", ""),
                "path": node.get("path", ""),
                "children_count": len(children),
            })
        for child in node.get("children", []):
            if isinstance(child, dict):
                SpecAssemblerNode._collect_inferred_nodes(child, results)

    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        components = inputs.get("components", [])
        page = inputs.get("page", {})
        design_tokens = inputs.get("design_tokens", {})
        source = inputs.get("source", {})
        output_dir = self.config.get("output_dir") or inputs.get("output_dir", "")

        logger.info(
            "SpecAssemblerNode [%s]: assembling %d components",
            self.node_id, len(components),
        )

        # Add exported_at timestamp + figma_last_modified passthrough
        source_with_ts = {
            **source,
            "exported_at": datetime.now(timezone.utc).isoformat(),
        }
        # Preserve figma_last_modified if provided by upstream
        if inputs.get("figma_last_modified"):
            source_with_ts["figma_last_modified"] = inputs["figma_last_modified"]

        # Sort components by z_index (bottom layer first)
        sorted_components = sorted(
            components,
            key=lambda c: c.get("z_index", 0),
        )

        # --- Deduplicate top-level component names ---
        # Parallel LLM calls may independently pick the same suggested_name.
        # Add position-based suffix to disambiguate (e.g. "Image" -> "Image_Top", "Image_Bottom").
        name_counts: Dict[str, int] = {}
        for comp in sorted_components:
            cname = comp.get("name", "Component")
            name_counts[cname] = name_counts.get(cname, 0) + 1

        name_seen: Dict[str, int] = {}
        dedup_count = 0
        for comp in sorted_components:
            cname = comp.get("name", "Component")
            if name_counts[cname] > 1:
                idx = name_seen.get(cname, 0) + 1
                name_seen[cname] = idx
                comp["name"] = f"{cname}_{idx}"
                dedup_count += 1
        if dedup_count > 0:
            logger.warning(
                "SpecAssemblerNode [%s]: deduplicated %d top-level component names",
                self.node_id, dedup_count,
            )

        # --- Quality validation (merge reports + role/bounds/hint/naming) ---
        from ..spec.spec_validator import run_all_validations
        quality_report = run_all_validations(
            sorted_components, page, node_id=self.node_id,
        )

        # --- Validate auto-layout compliance ---
        inferred_nodes: List[Dict[str, Any]] = []
        for comp in sorted_components:
            self._collect_inferred_nodes(comp, inferred_nodes)

        # Build combined validation report
        validation: Dict[str, Any] = {
            "auto_layout_compliant": len(inferred_nodes) == 0,
            "inferred_node_count": len(inferred_nodes),
            "inferred_nodes": inferred_nodes,
            **quality_report,
        }
        if inferred_nodes:
            validation["message"] = (
                f"{len(inferred_nodes)} node(s) missing auto-layout. "
                "These nodes have no precise gap/padding data from Figma. "
                "Please add auto-layout in Figma and re-run the pipeline."
            )
            logger.warning(
                "SpecAssemblerNode [%s]: %d node(s) missing auto-layout: %s",
                self.node_id,
                len(inferred_nodes),
                ", ".join(n["name"] for n in inferred_nodes[:10]),
            )

        # Assemble final document
        # Token usage stats from SpecAnalyzer (if provided)
        token_usage = inputs.get("token_usage")

        spec_document = {
            "version": "1.0",
            "spec_version": "1.0.0",
            "analyzer_version": "1.1.0",
            "source": source_with_ts,
            "page": page,
            "design_tokens": design_tokens,
            "components": sorted_components,
            "validation": validation,
        }
        if token_usage:
            spec_document["token_usage"] = token_usage

        # Write to disk if output_dir provided
        spec_path = ""
        if output_dir:
            os.makedirs(output_dir, exist_ok=True)
            spec_path = os.path.join(output_dir, "design_spec.json")
            with open(spec_path, "w", encoding="utf-8") as f:
                json.dump(spec_document, f, ensure_ascii=False, indent=2)
            logger.info(
                "SpecAssemblerNode [%s]: wrote %s (%d components, %d inferred, "
                "%d quality warnings)",
                self.node_id, spec_path, len(sorted_components),
                len(inferred_nodes),
                quality_report.get("quality_warning_count", 0),
            )

        return {
            "spec_path": spec_path,
            "spec_document": spec_document,
            "validation": validation,
        }
