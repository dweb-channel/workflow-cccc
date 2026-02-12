"""Workflow Template API endpoints.

Provides pre-defined workflow templates that users can load into the editor.
Templates are stored as JSON files in workflow/templates/ directory.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v2/templates", tags=["templates"])

# Template directory path (relative to backend_fastapi)
TEMPLATES_DIR = Path(__file__).parent.parent.parent / "workflow" / "templates"


class TemplateListItem(BaseModel):
    """Template summary for list endpoint."""
    name: str
    title: str
    description: str
    icon: Optional[str] = None
    category: str = "graph"  # 'graph' = editable workflow, 'page' = standalone page
    path: Optional[str] = None  # frontend route for 'page' category


class NodePosition(BaseModel):
    """Node position on canvas."""
    x: float
    y: float


class TemplateNodeData(BaseModel):
    """Node data containing label and config (matches frontend format)."""
    label: str
    config: Dict[str, Any]


class TemplateNode(BaseModel):
    """Node definition in template (matches frontend React Flow format)."""
    id: str
    type: str
    position: NodePosition
    data: TemplateNodeData


class TemplateEdge(BaseModel):
    """Edge definition in template."""
    id: str
    source: str
    target: str
    condition: Optional[str] = None


class TemplateDetail(BaseModel):
    """Full template detail for get endpoint."""
    name: str
    title: str
    description: str
    icon: Optional[str] = None
    max_iterations: Optional[int] = None
    nodes: List[TemplateNode]
    edges: List[TemplateEdge]
    entry_point: Optional[str] = None


def _load_template(name: str) -> Optional[Dict[str, Any]]:
    """Load a template JSON file by name."""
    template_path = TEMPLATES_DIR / f"{name}.json"
    if not template_path.exists():
        return None
    try:
        with open(template_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        logger.error(f"Failed to load template {name}: {e}")
        return None


def _list_templates() -> List[Dict[str, Any]]:
    """List all available templates."""
    templates = []
    if not TEMPLATES_DIR.exists():
        return templates

    for path in TEMPLATES_DIR.glob("*.json"):
        data = _load_template(path.stem)
        if data:
            templates.append(data)
    return templates


def _parse_node(n: Dict[str, Any]) -> TemplateNode:
    """Parse a node from template JSON, supporting both old and new formats.

    New format (frontend): node.data.label, node.data.config
    Old format (legacy): node.config with node.config.name as label
    """
    if "data" in n:
        # New format: data.label, data.config
        node_data = n["data"]
        label = node_data.get("label", node_data.get("config", {}).get("name", ""))
        config = node_data.get("config", {})
    else:
        # Legacy format: config at top level
        config = n.get("config", {})
        label = config.get("name", "")

    return TemplateNode(
        id=n["id"],
        type=n["type"],
        position=NodePosition(**n["position"]),
        data=TemplateNodeData(label=label, config=config),
    )


# Hardcoded page-type templates (not backed by JSON workflow files)
_PAGE_TEMPLATES: List[TemplateListItem] = [
    TemplateListItem(
        name="batch-bug-fix",
        title="批量 Bug 修复",
        icon="bug",
        description="批量提交多个 Bug，自动依次分析修复",
        category="page",
        path="/batch-bugs",
    ),
]


@router.get("", response_model=List[TemplateListItem])
async def list_templates() -> List[TemplateListItem]:
    """List all available workflow templates.

    Returns a list of template summaries with category metadata.
    Category 'graph' = editable workflow template, 'page' = standalone page.
    """
    templates = _list_templates()
    items = [
        TemplateListItem(
            name=t["name"],
            title=t["title"],
            description=t["description"],
            icon=t.get("icon"),
            category=t.get("category", "graph"),
        )
        for t in templates
    ]
    items.extend(_PAGE_TEMPLATES)
    return items


@router.get("/{name}", response_model=TemplateDetail)
async def get_template(name: str) -> TemplateDetail:
    """Get a specific workflow template by name.

    Returns full template detail including nodes and edges.
    Nodes are returned in frontend-compatible format with data.label and data.config.
    """
    data = _load_template(name)
    if data is None:
        raise HTTPException(status_code=404, detail=f"Template '{name}' not found")

    return TemplateDetail(
        name=data["name"],
        title=data["title"],
        description=data["description"],
        icon=data.get("icon"),
        max_iterations=data.get("max_iterations"),
        nodes=[_parse_node(n) for n in data.get("nodes", [])],
        edges=[
            TemplateEdge(
                id=e["id"],
                source=e["source"],
                target=e["target"],
                condition=e.get("condition"),
            )
            for e in data.get("edges", [])
        ],
        entry_point=data.get("entry_point"),
    )
