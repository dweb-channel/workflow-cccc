"""Workflow Templates Module.

Provides utilities for loading and validating workflow templates.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

TEMPLATES_DIR = Path(__file__).parent


def load_template(name: str) -> Dict[str, Any]:
    """Load a workflow template by name.

    Args:
        name: Template name (without .json extension)

    Returns:
        Template configuration dictionary

    Raises:
        FileNotFoundError: If template does not exist
        json.JSONDecodeError: If template is not valid JSON
    """
    template_path = TEMPLATES_DIR / f"{name}.json"
    if not template_path.exists():
        raise FileNotFoundError(f"Template '{name}' not found at {template_path}")

    with open(template_path, "r", encoding="utf-8") as f:
        return json.load(f)


def list_templates() -> list[str]:
    """List all available workflow templates.

    Returns:
        List of template names (without .json extension)
    """
    return [p.stem for p in TEMPLATES_DIR.glob("*.json")]


def template_to_workflow_definition(template: Dict[str, Any]) -> Dict[str, Any]:
    """Convert template format to WorkflowDefinition compatible format.

    Args:
        template: Raw template dictionary

    Returns:
        Dictionary compatible with WorkflowDefinition dataclass
    """
    return {
        "name": template.get("name", "unnamed_workflow"),
        "nodes": [
            {
                "id": node["id"],
                "type": node["type"],
                "config": node.get("config", {}),
            }
            for node in template.get("nodes", [])
        ],
        "edges": [
            {
                "id": edge["id"],
                "source": edge["source"],
                "target": edge["target"],
                "condition": edge.get("condition"),
            }
            for edge in template.get("edges", [])
        ],
        "entry_point": template.get("entry_point"),
        "max_iterations": template.get("max_iterations", 10),
    }


def instantiate_template(
    name: str,
    overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Load and instantiate a template with optional overrides.

    Args:
        name: Template name
        overrides: Optional config overrides per node (keyed by node_id)

    Returns:
        Instantiated workflow configuration

    Example:
        workflow = instantiate_template(
            "bug_fix_batch",
            overrides={
                "fix_bug_peer": {"peer_id": "custom-fixer", "timeout": 600},
            }
        )
    """
    template = load_template(name)
    overrides = overrides or {}

    # Apply overrides to node configs
    for node in template.get("nodes", []):
        node_id = node["id"]
        if node_id in overrides:
            node["config"].update(overrides[node_id])

    return template_to_workflow_definition(template)
