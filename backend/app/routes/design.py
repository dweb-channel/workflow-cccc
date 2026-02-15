"""Design-to-Code API endpoints.

Provides endpoints for running design-to-code workflows that convert
Figma design exports into React + Tailwind code.

Execution is async (background task) with SSE progress streaming.
No Temporal dependency — uses asyncio for POC validation.
"""

from __future__ import annotations

import asyncio
import html
import json
import logging
import os
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import unquote

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session, get_session_ctx
from app.models.db import DesignJobModel
from app.repositories.design_job import DesignJobRepository
from app.sse import push_node_event, sse_event_generator

logger = logging.getLogger("workflow.routes.design")

router = APIRouter(prefix="/api/v2/design", tags=["design"])


# --- Schemas ---


class DesignRunRequest(BaseModel):
    """Request for POST /api/v2/design/run."""

    design_file: str = Field(
        ..., description="Path to design_export.json file"
    )
    output_dir: str = Field(
        ..., description="Target directory for generated code"
    )
    cwd: Optional[str] = Field(
        None, description="Working directory for Claude CLI"
    )
    max_retries: int = Field(
        default=2, ge=0, le=5, description="Max retries per component"
    )


class DesignRunResponse(BaseModel):
    """Response for POST /api/v2/design/run."""

    job_id: str
    status: str
    design_file: str
    output_dir: str
    created_at: str


class DesignJobStatus(BaseModel):
    """Response for GET /api/v2/design/{job_id}."""

    job_id: str
    status: str
    design_file: str
    output_dir: str
    created_at: str
    completed_at: Optional[str] = None
    error: Optional[str] = None
    components_total: int = 0
    components_completed: int = 0
    components_failed: int = 0
    result: Optional[Dict[str, Any]] = None


class DesignFileEntry(BaseModel):
    """Single file entry in the files response."""

    path: str = Field(..., description="Relative path from output_dir")
    content: str = Field(..., description="File content as text")
    size: int = Field(..., description="File size in bytes")


class FigmaRunRequest(BaseModel):
    """Request for POST /api/v2/design/run-figma.

    Two modes:
    1. Simple: just figma_url (node-id parsed from URL) — Sprint 2 compat
    2. Selected: figma_url + selected_screens (from /scan-figma confirm) — Sprint 3
    """

    figma_url: str = Field(
        ...,
        description=(
            "Figma URL, e.g. https://www.figma.com/design/{fileKey}/{name}?node-id={nodeId}"
        ),
    )
    output_dir: str = Field(
        ..., description="Target directory for generated code"
    )
    cwd: Optional[str] = Field(
        None, description="Working directory for Claude CLI"
    )
    max_retries: int = Field(
        default=2, ge=0, le=5, description="Max retries per component"
    )
    selected_screens: Optional[List[Dict[str, Any]]] = Field(
        None,
        description=(
            "Screens selected by user after /scan-figma. "
            "Each item: { node_id: str, interaction_note_ids: [str] }. "
            "If omitted, falls back to parsing node-id from URL."
        ),
    )


class SpecRunRequest(BaseModel):
    """Request for POST /api/v2/design/run-spec.

    Runs the 3-node spec pipeline (FrameDecomposer → SpecAnalyzer → SpecAssembler)
    against a Figma page to produce a structured design_spec.json.
    """

    figma_url: str = Field(
        ...,
        description=(
            "Figma URL, e.g. https://www.figma.com/design/{fileKey}/{name}?node-id={nodeId}"
        ),
    )
    output_dir: str = Field(
        ..., description="Target directory for generated spec"
    )
    model: Optional[str] = Field(
        None,
        description=(
            "Model for SpecAnalyzer vision analysis. "
            "Optional — omit to use CLI default. Accepts aliases (sonnet, opus) or full model IDs."
        ),
    )


class FigmaScanRequest(BaseModel):
    """Request for POST /api/v2/design/scan-figma."""

    figma_url: str = Field(
        ...,
        description="Figma page URL to scan for UI screens and interaction specs",
    )


class ScanFrameItem(BaseModel):
    """Single frame in scan results."""

    node_id: str
    name: str
    size: str = Field(..., description="WxH string, e.g. '393×852'")
    bounds: Dict[str, float] = Field(default_factory=dict)
    classification: str = Field(
        ..., description="ui_screen | interaction_spec | design_system | reference | other"
    )
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    text_content: List[str] = Field(default_factory=list)
    thumbnail_url: Optional[str] = None
    related_to: Optional[str] = Field(
        None, description="node_id of related UI screen (for interaction specs)"
    )
    section: Optional[str] = Field(
        None, description="Parent section name if nested in a section"
    )
    device_type: Optional[str] = Field(
        None, description="mobile | tablet | desktop"
    )


class FigmaScanResponse(BaseModel):
    """Response for POST /api/v2/design/scan-figma."""

    file_key: str
    page_name: str
    candidates: List[ScanFrameItem] = Field(
        default_factory=list, description="UI screen frames"
    )
    interaction_specs: List[ScanFrameItem] = Field(
        default_factory=list, description="Interaction/annotation frames"
    )
    design_system: List[ScanFrameItem] = Field(
        default_factory=list, description="Design system/token frames"
    )
    excluded: List[ScanFrameItem] = Field(
        default_factory=list, description="Excluded frames with reasons"
    )
    warnings: List[str] = Field(
        default_factory=list, description="Diagnostic warnings (e.g. target node too small)"
    )


class DesignFilesResponse(BaseModel):
    """Response for GET /api/v2/design/{job_id}/files."""

    job_id: str
    status: str
    output_dir: str
    files: List[DesignFileEntry] = []


def _job_to_status(job: DesignJobModel) -> DesignJobStatus:
    """Convert ORM model to Pydantic response."""
    return DesignJobStatus(
        job_id=job.id,
        status=job.status,
        design_file=job.design_file,
        output_dir=job.output_dir,
        created_at=job.created_at.isoformat() if job.created_at else "",
        completed_at=job.completed_at.isoformat() if job.completed_at else None,
        error=job.error,
        components_total=job.components_total,
        components_completed=job.components_completed,
        components_failed=job.components_failed,
        result=job.result,
    )


def _job_to_dict(job: DesignJobModel) -> Dict[str, Any]:
    """Convert ORM model to dict for SSE JSON serialization."""
    return {
        "job_id": job.id,
        "status": job.status,
        "design_file": job.design_file,
        "output_dir": job.output_dir,
        "cwd": job.cwd,
        "max_retries": job.max_retries,
        "created_at": job.created_at.isoformat() if job.created_at else "",
        "completed_at": job.completed_at.isoformat() if job.completed_at else None,
        "error": job.error,
        "components_total": job.components_total,
        "components_completed": job.components_completed,
        "components_failed": job.components_failed,
        "result": job.result,
    }


# --- Endpoints ---


@router.post("/run", response_model=DesignRunResponse, status_code=201)
async def run_design_to_code(
    payload: DesignRunRequest,
    session: AsyncSession = Depends(get_session),
):
    """Start a design-to-code workflow.

    Takes a design_export.json file path and output directory,
    runs the full pipeline (analyze → skeleton → component loop → assemble),
    and streams progress via SSE.

    Usage:
        POST /api/v2/design/run
        {
            "design_file": "data/design_export/design_export.json",
            "output_dir": "output/generated",
            "max_retries": 2
        }
    """
    # Validate design file exists
    design_path = os.path.abspath(payload.design_file)
    if not os.path.isfile(design_path):
        raise HTTPException(
            status_code=400,
            detail=f"Design file not found: {design_path}",
        )

    # Validate it's valid JSON
    try:
        with open(design_path, "r", encoding="utf-8") as f:
            design_data = json.load(f)
    except json.JSONDecodeError as e:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid JSON in design file: {e}",
        )

    # Create output directory if needed
    output_dir = os.path.abspath(payload.output_dir)
    os.makedirs(output_dir, exist_ok=True)

    # Create job in DB
    job_id = f"design_{uuid.uuid4().hex[:12]}"
    repo = DesignJobRepository(session)
    job = await repo.create(
        job_id=job_id,
        design_file=design_path,
        output_dir=output_dir,
        cwd=payload.cwd or os.getcwd(),
        max_retries=payload.max_retries,
    )

    logger.info(f"Job {job_id}: Created design-to-code job, design={design_path}")

    # Start async execution in background with error tracking
    task = asyncio.create_task(_execute_design_pipeline(job_id))
    task.add_done_callback(lambda t: _on_pipeline_task_done(t, job_id))

    return DesignRunResponse(
        job_id=job_id,
        status="started",
        design_file=design_path,
        output_dir=output_dir,
        created_at=job.created_at.isoformat(),
    )


@router.post("/scan-figma", response_model=FigmaScanResponse)
async def scan_figma_page(payload: FigmaScanRequest):
    """Scan a Figma page and classify frames into UI screens, interaction specs, etc.

    Synchronous endpoint — returns classification results for user confirmation
    before starting the pipeline. Does not create a job.

    Flow: scan-figma → user confirms → run-figma (with selected_screens)

    Requires FIGMA_TOKEN environment variable.

    Usage:
        POST /api/v2/design/scan-figma
        { "figma_url": "https://www.figma.com/design/6kGd851.../PixelCheese?node-id=2172-2255" }
    """
    from workflow.config import FIGMA_TOKEN
    if not FIGMA_TOKEN:
        raise HTTPException(
            status_code=400,
            detail=(
                "Figma integration not configured. "
                "Set FIGMA_TOKEN environment variable with a valid Figma Personal Access Token. "
                "See: https://www.figma.com/developers/api#access-tokens"
            ),
        )

    # Parse URL for file_key and page node_id
    file_key, page_node_id = _parse_figma_url(payload.figma_url)

    from workflow.integrations.figma_client import FigmaClient, FigmaClientError

    try:
        client = FigmaClient()
    except FigmaClientError as e:
        raise HTTPException(status_code=400, detail=str(e))

    try:
        # P2: Auto-resolve small component → parent page
        scan_node_id = page_node_id
        extra_warnings: List[str] = []
        try:
            node_data = await client.get_file_nodes(file_key, [page_node_id])
            node_doc = node_data.get("nodes", {}).get(page_node_id, {}).get("document", {})
            resolved = await client.resolve_to_page(file_key, page_node_id, node_doc)
            if resolved:
                scan_node_id = resolved["page_id"]
                node_name = node_doc.get("name", page_node_id)
                extra_warnings.append(
                    f"URL 中的 node-id 指向 \"{node_name}\"，不是完整页面。"
                    f"已自动切换到页面 \"{resolved['page_name']}\" 进行扫描。"
                )
                logger.info(
                    f"scan-figma: auto-resolved {page_node_id} → page {resolved['page_id']} "
                    f"(\"{resolved['page_name']}\")"
                )
        except Exception as e:
            logger.warning(f"scan-figma: resolve_to_page failed, using original node: {e}")

        # Phase 1+2: Scan and classify frames (rules + LLM)
        scan_result = await client.scan_and_classify_frames(
            file_key=file_key,
            page_node_id=scan_node_id,
        )

        # Merge extra warnings from P2 resolve
        if extra_warnings:
            scan_warnings = scan_result.get("warnings", [])
            scan_result["warnings"] = extra_warnings + scan_warnings

        # Collect all candidate node_ids for thumbnail generation
        all_node_ids = []
        for category in ("candidates", "interaction_specs", "design_system"):
            for item in scan_result.get(category, []):
                if item.get("node_id"):
                    all_node_ids.append(item["node_id"])

        # Fetch thumbnails for candidate frames
        thumbnail_urls: Dict[str, Optional[str]] = {}
        if all_node_ids:
            try:
                thumbnail_urls = await client.get_node_images(
                    file_key, all_node_ids, fmt="png", scale=1,
                )
            except FigmaClientError as e:
                logger.warning(f"scan-figma: Failed to get thumbnails: {e}")

        # Attach thumbnail URLs to scan results
        for category in ("candidates", "interaction_specs", "design_system"):
            for item in scan_result.get(category, []):
                nid = item.get("node_id", "")
                if nid in thumbnail_urls:
                    item["thumbnail_url"] = thumbnail_urls[nid]

        # Build response — merge 'unknown' into 'excluded' until LLM classifier is wired
        def _items_to_models(items: List[Dict]) -> List[ScanFrameItem]:
            result = []
            for item in items:
                # Ensure required fields have defaults for ScanFrameItem
                item.setdefault("classification", "other")
                item.setdefault("size", "0×0")
                # Normalize related_to: D1 may return a dict {node_id, name}
                rt = item.get("related_to")
                if isinstance(rt, dict):
                    item["related_to"] = rt.get("node_id")
                result.append(ScanFrameItem(**{
                    k: v for k, v in item.items()
                    if k in ScanFrameItem.model_fields
                }))
            return result

        excluded_items = scan_result.get("excluded", [])
        unknown_items = scan_result.get("unknown", [])
        for item in unknown_items:
            item["classification"] = "other"
        all_excluded = excluded_items + unknown_items

        return FigmaScanResponse(
            file_key=file_key,
            page_name=scan_result.get("page_name", ""),
            candidates=_items_to_models(scan_result.get("candidates", [])),
            interaction_specs=_items_to_models(scan_result.get("interaction_specs", [])),
            design_system=_items_to_models(scan_result.get("design_system", [])),
            excluded=_items_to_models(all_excluded),
            warnings=scan_result.get("warnings", []),
        )

    except FigmaClientError as e:
        raise HTTPException(status_code=502, detail=f"Figma API error: {e}")
    finally:
        await client.close()


@router.post("/run-figma", response_model=DesignRunResponse, status_code=201)
async def run_figma_to_code(
    payload: FigmaRunRequest,
    session: AsyncSession = Depends(get_session),
):
    """Start a design-to-code workflow from a Figma URL.

    Two modes:
    1. Simple (Sprint 2): just figma_url with node-id in URL
    2. Selected (Sprint 3): figma_url + selected_screens from /scan-figma

    Requires FIGMA_TOKEN environment variable.

    Usage (simple):
        POST /api/v2/design/run-figma
        {
            "figma_url": "https://www.figma.com/design/6kGd851.../PixelCheese?node-id=16650-538",
            "output_dir": "output/generated",
            "max_retries": 2
        }

    Usage (selected):
        POST /api/v2/design/run-figma
        {
            "figma_url": "https://www.figma.com/design/6kGd851.../PixelCheese",
            "output_dir": "output/generated",
            "selected_screens": [
                { "node_id": "16650:538", "interaction_note_ids": ["16650:600"] }
            ]
        }
    """
    # Fail fast if FIGMA_TOKEN is not configured
    from workflow.config import FIGMA_TOKEN
    if not FIGMA_TOKEN:
        raise HTTPException(
            status_code=400,
            detail=(
                "Figma integration not configured. "
                "Set FIGMA_TOKEN environment variable with a valid Figma Personal Access Token. "
                "See: https://www.figma.com/developers/api#access-tokens"
            ),
        )

    # Extract file_key from URL (always needed)
    file_key, _ = _parse_figma_url_file_key(payload.figma_url)

    # Determine target node(s)
    if payload.selected_screens:
        # Sprint 3 mode: user selected specific screens from /scan-figma
        node_ids = [s["node_id"] for s in payload.selected_screens]
        node_id = node_ids[0]  # Primary node for job tracking
        interaction_note_ids = []
        for s in payload.selected_screens:
            interaction_note_ids.extend(s.get("interaction_note_ids", []))
    else:
        # Sprint 2 compat: parse node-id from URL
        _, node_id = _parse_figma_url(payload.figma_url)
        node_ids = [node_id]
        interaction_note_ids = []

    # Create output directory
    output_dir = os.path.abspath(payload.output_dir)
    os.makedirs(output_dir, exist_ok=True)

    # Create job in DB (design_file will be set after Figma fetch)
    job_id = f"design_{uuid.uuid4().hex[:12]}"
    design_export_path = os.path.join(output_dir, "design_export.json")
    repo = DesignJobRepository(session)
    job = await repo.create(
        job_id=job_id,
        design_file=design_export_path,
        output_dir=output_dir,
        cwd=payload.cwd or os.getcwd(),
        max_retries=payload.max_retries,
    )

    logger.info(
        f"Job {job_id}: Created Figma design-to-code job, "
        f"file_key={file_key}, node_ids={node_ids}"
    )

    # Start async execution: Figma fetch → pipeline
    task = asyncio.create_task(
        _execute_figma_pipeline(
            job_id, file_key, node_id,
            interaction_note_ids=interaction_note_ids,
        )
    )
    task.add_done_callback(lambda t: _on_pipeline_task_done(t, job_id))

    return DesignRunResponse(
        job_id=job_id,
        status="started",
        design_file=design_export_path,
        output_dir=output_dir,
        created_at=job.created_at.isoformat(),
    )


@router.post("/run-spec", response_model=DesignRunResponse, status_code=201)
async def run_spec_pipeline(
    payload: SpecRunRequest,
    session: AsyncSession = Depends(get_session),
):
    """Start a spec generation pipeline from a Figma URL.

    Runs the 3-node spec pipeline:
      1. FrameDecomposer — extracts structural data from Figma node tree (70%)
      2. SpecAnalyzer — LLM vision fills semantic fields (role, description, interaction)
      3. SpecAssembler — assembles final design_spec.json

    SSE events:
      - frame_decomposed: Node 1 complete, partial specs available
      - spec_analyzed: Per-component, semantic fields filled
      - spec_complete: Final spec written to disk
      - job_done: Pipeline finished

    Requires FIGMA_TOKEN environment variable.

    Usage:
        POST /api/v2/design/run-spec
        {
            "figma_url": "https://www.figma.com/design/6kGd851.../PixelCheese?node-id=5574-3309",
            "output_dir": "output/spec"
        }
    """
    from workflow.config import FIGMA_TOKEN
    if not FIGMA_TOKEN:
        raise HTTPException(
            status_code=400,
            detail=(
                "Figma integration not configured. "
                "Set FIGMA_TOKEN environment variable with a valid Figma Personal Access Token. "
                "See: https://www.figma.com/developers/api#access-tokens"
            ),
        )

    # Parse Figma URL
    file_key, node_id = _parse_figma_url(payload.figma_url)

    # Create output directory
    output_dir = os.path.abspath(payload.output_dir)
    os.makedirs(output_dir, exist_ok=True)

    # Create job in DB
    job_id = f"spec_{uuid.uuid4().hex[:12]}"
    spec_path = os.path.join(output_dir, "design_spec.json")
    repo = DesignJobRepository(session)
    job = await repo.create(
        job_id=job_id,
        design_file=spec_path,
        output_dir=output_dir,
        cwd=os.getcwd(),
        max_retries=0,
    )

    logger.info(
        f"Job {job_id}: Created spec pipeline job, "
        f"file_key={file_key}, node_id={node_id}"
    )

    # Start async execution
    task = asyncio.create_task(
        _execute_spec_pipeline(
            job_id=job_id,
            file_key=file_key,
            node_id=node_id,
            output_dir=output_dir,
            model=payload.model,
        )
    )
    task.add_done_callback(lambda t: _on_pipeline_task_done(t, job_id))

    return DesignRunResponse(
        job_id=job_id,
        status="started",
        design_file=spec_path,
        output_dir=output_dir,
        created_at=job.created_at.isoformat(),
    )


@router.get("/{job_id}", response_model=DesignJobStatus)
async def get_design_job_status(
    job_id: str,
    session: AsyncSession = Depends(get_session),
):
    """Get the current status of a design-to-code job."""
    repo = DesignJobRepository(session)
    job = await repo.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")

    return _job_to_status(job)


@router.get("/{job_id}/stream")
async def stream_design_job_progress(
    job_id: str,
    session: AsyncSession = Depends(get_session),
):
    """Stream real-time progress updates for a design-to-code job via SSE.

    Events:
    - job_state: Initial job state when connected
    - workflow_start: Pipeline started
    - node_started / node_completed: Per-node progress
    - component_started / component_completed / component_failed: Per-component
    - loop_iteration: Component loop progress
    - workflow_complete: Pipeline finished
    - workflow_error: Pipeline failed
    - job_done: Final event (always sent)

    Usage:
        const sse = new EventSource('/api/v2/design/{job_id}/stream');
        sse.addEventListener('component_completed', (e) => console.log(JSON.parse(e.data)));
    """
    repo = DesignJobRepository(session)
    job = await repo.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")

    # Snapshot job state for initial SSE event (session closes after handler returns)
    initial_state = _job_to_dict(job)

    return StreamingResponse(
        _design_sse_generator(job_id, initial_state),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("", response_model=List[DesignJobStatus])
async def list_design_jobs(
    session: AsyncSession = Depends(get_session),
):
    """List all design-to-code jobs."""
    repo = DesignJobRepository(session)
    jobs, _ = await repo.list()
    return [_job_to_status(job) for job in jobs]


@router.post("/{job_id}/cancel")
async def cancel_design_job(
    job_id: str,
    session: AsyncSession = Depends(get_session),
):
    """Cancel a running design-to-code job."""
    repo = DesignJobRepository(session)
    job = await repo.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")

    if job.status in ("completed", "failed", "cancelled"):
        return {"success": False, "job_id": job_id, "status": job.status,
                "message": f"Job already {job.status}"}

    await repo.update_status(
        job_id, "cancelled",
        completed_at=datetime.now(timezone.utc),
    )

    # Push job_done event so SSE clients close
    push_node_event(job_id, "job_done", {
        "status": "cancelled",
        "components_total": job.components_total,
        "components_completed": job.components_completed,
        "components_failed": job.components_failed,
    })

    return {"success": True, "job_id": job_id, "status": "cancelled"}


# Allowed file extensions for the files endpoint
_CODE_EXTENSIONS = {".tsx", ".ts", ".jsx", ".js", ".css", ".json", ".html"}


@router.get("/{job_id}/files", response_model=DesignFilesResponse)
async def get_design_job_files(
    job_id: str,
    session: AsyncSession = Depends(get_session),
):
    """Get the generated code files for a completed design-to-code job.

    Recursively scans the job's output_dir for code files (.tsx, .ts, .css, etc.)
    and returns their paths and contents.

    If the job is still running, returns an empty file list with status.

    Usage:
        GET /api/v2/design/{job_id}/files
        → { job_id, status, output_dir, files: [{ path, content, size }] }
    """
    repo = DesignJobRepository(session)
    job = await repo.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")

    output_dir = job.output_dir
    files: List[DesignFileEntry] = []

    # Only scan files if job is completed (or failed — partial results may exist)
    if job.status in ("completed", "failed") and os.path.isdir(output_dir):
        for dirpath, _, filenames in os.walk(output_dir):
            for filename in sorted(filenames):
                ext = os.path.splitext(filename)[1].lower()
                if ext not in _CODE_EXTENSIONS:
                    continue
                abs_path = os.path.join(dirpath, filename)
                rel_path = os.path.relpath(abs_path, output_dir)
                try:
                    with open(abs_path, "r", encoding="utf-8") as f:
                        content = f.read()
                    files.append(DesignFileEntry(
                        path=rel_path,
                        content=content,
                        size=os.path.getsize(abs_path),
                    ))
                except (OSError, UnicodeDecodeError) as e:
                    logger.warning(f"Job {job_id}: Skipping file {rel_path}: {e}")

    # Sort by path for consistent ordering
    files.sort(key=lambda f: f.path)

    return DesignFilesResponse(
        job_id=job_id,
        status=job.status,
        output_dir=output_dir,
        files=files,
    )


@router.get("/{job_id}/preview")
async def preview_design_job(
    job_id: str,
    session: AsyncSession = Depends(get_session),
):
    """Render generated code as a self-contained HTML preview page.

    Returns an HTML page that uses React CDN + Babel standalone + Tailwind CDN
    to render the generated components in-browser. Can be loaded directly or
    embedded in an iframe.

    Usage:
        GET /api/v2/design/{job_id}/preview
        → text/html page with live-rendered components
    """
    repo = DesignJobRepository(session)
    job = await repo.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")

    output_dir = job.output_dir

    if not os.path.isdir(output_dir):
        raise HTTPException(status_code=404, detail="Output directory not found")

    # Collect generated files
    css_content = ""
    component_sources = []  # (name, code) — components first, Page last
    page_source = ""

    for dirpath, _, filenames in os.walk(output_dir):
        for filename in sorted(filenames):
            abs_path = os.path.join(dirpath, filename)
            rel_path = os.path.relpath(abs_path, output_dir)
            try:
                with open(abs_path, "r", encoding="utf-8") as f:
                    content = f.read()
            except (OSError, UnicodeDecodeError):
                continue

            if filename.endswith(".css"):
                css_content += content + "\n"
            elif filename.endswith((".tsx", ".ts", ".jsx", ".js")):
                cleaned = _strip_imports_exports(content)
                if rel_path == "Page.tsx" or rel_path.endswith("/Page.tsx"):
                    page_source = cleaned
                else:
                    component_sources.append((filename, cleaned))

    # Build all JS code: components first, then Page, then render
    all_js = "\n\n".join(code for _, code in component_sources)
    if page_source:
        all_js += "\n\n" + page_source
    all_js += "\n\nReactDOM.createRoot(document.getElementById('root')).render(React.createElement(Page));"

    html_page = _build_preview_html(css_content, all_js, job_id)
    return HTMLResponse(content=html_page)


def _strip_imports_exports(code: str) -> str:
    """Strip import/export statements from TSX code for browser execution.

    - Removes `import ... from '...'` lines
    - Converts `export default function X` → `function X`
    - Converts `export function X` → `function X`
    - Converts `export interface X` → `interface X` (Babel TS preset removes these)
    - Converts `export type X` → `type X`
    """
    lines = []
    for line in code.split("\n"):
        stripped = line.strip()
        # Skip import lines
        if stripped.startswith("import ") and (" from " in stripped or stripped.endswith(";")):
            continue
        # Strip export keywords
        line = re.sub(r"^(\s*)export\s+default\s+function\b", r"\1function", line)
        line = re.sub(r"^(\s*)export\s+function\b", r"\1function", line)
        line = re.sub(r"^(\s*)export\s+interface\b", r"\1interface", line)
        line = re.sub(r"^(\s*)export\s+type\b", r"\1type", line)
        line = re.sub(r"^(\s*)export\s+const\b", r"\1const", line)
        lines.append(line)
    return "\n".join(lines)


def _build_tailwind_fallbacks(js_code: str) -> str:
    """Generate CSS fallback rules for non-standard Tailwind classes.

    Figma MCP's get_design_context generates code with classes that may not
    exist in Tailwind v3 CDN. This function scans the JS code and emits
    matching CSS rules as fallbacks.

    Covers:
    - content-stretch → align-content: stretch
    - bg-top-left → background-position: top left
    - bg-size-[...] → background-size: ...
    - size-full → width: 100%; height: 100%
    - size-[Xpx] → width: X; height: X
    - col-1 / row-1 → grid-column / grid-row
    - overflow-clip → overflow: clip
    """
    rules = []

    if "content-stretch" in js_code:
        rules.append(".content-stretch { align-content: stretch; }")

    if "bg-top-left" in js_code:
        rules.append(".bg-top-left { background-position: top left; }")

    if "overflow-clip" in js_code:
        rules.append(".overflow-clip { overflow: clip; }")

    if "size-full" in js_code:
        rules.append(".size-full { width: 100%; height: 100%; }")

    if "col-1" in js_code:
        rules.append(".col-1 { grid-column: 1; }")

    if "row-1" in js_code:
        rules.append(".row-1 { grid-row: 1; }")

    # bg-size-[WxH] — arbitrary background-size values
    seen_bg_sizes: set = set()
    for m in re.finditer(r'bg-size-\[([^\]]+)\]', js_code):
        raw = m.group(1)
        if raw in seen_bg_sizes:
            continue
        seen_bg_sizes.add(raw)
        val = raw.replace("_", " ")
        cls = f"bg-size-\\[{re.escape(raw)}\\]"
        rules.append(f'.{cls} {{ background-size: {val}; }}')

    # size-[Xpx] — arbitrary width+height values (fallback if CDN doesn't handle)
    # Use negative lookbehind to avoid matching bg-size-[...]
    seen_sizes: set = set()
    for m in re.finditer(r'(?<!bg-)size-\[([^\]]+)\]', js_code):
        val = m.group(1)
        if val in seen_sizes:
            continue
        seen_sizes.add(val)
        cls = f"size-\\[{re.escape(val)}\\]"
        rules.append(f'.{cls} {{ width: {val}; height: {val}; }}')

    return "\n        ".join(rules)


def _build_preview_html(css: str, js_code: str, job_id: str) -> str:
    """Build a self-contained HTML page for preview rendering."""
    # Script content must NOT be HTML-escaped — only guard against </script> in code
    safe_js = js_code.replace("</script>", "<\\/script>")

    # Generate CSS fallbacks for non-standard Tailwind classes
    tw_fallbacks = _build_tailwind_fallbacks(js_code)

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Preview — {html.escape(job_id)}</title>
    <script src="https://unpkg.com/react@18/umd/react.production.min.js" crossorigin></script>
    <script src="https://unpkg.com/react-dom@18/umd/react-dom.production.min.js" crossorigin></script>
    <script src="https://unpkg.com/@babel/standalone/babel.min.js"></script>
    <script src="https://cdn.tailwindcss.com"></script>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ display: flex; justify-content: center; background: #f0f0f0; min-height: 100vh; padding: 16px 0; }}
        #root {{ background: #fff; }}
        /* Tailwind fallbacks for Figma MCP generated classes */
        {tw_fallbacks}
        {css}
    </style>
</head>
<body>
    <div id="root"></div>
    <script type="text/babel" data-presets="typescript,react">
{safe_js}
    </script>
</body>
</html>"""


# --- SSE Generator ---


async def _design_sse_generator(job_id: str, initial_state: Dict[str, Any]):
    """SSE generator for design job progress.

    Sends initial job state, then streams real-time events.

    Args:
        job_id: Job identifier for SSE event subscription
        initial_state: Snapshot of job state for the first SSE event
    """
    yield f"event: job_state\ndata: {json.dumps(initial_state, default=str)}\n\n"

    # Stream from shared SSE infrastructure
    async for event_str in sse_event_generator(job_id):
        yield event_str
        if event_str.startswith("event: job_done\n"):
            break


# --- Figma URL Parsing ---


def _parse_figma_url(url: str) -> tuple:
    """Parse a Figma URL into (file_key, node_id).

    Supports:
        https://www.figma.com/design/{fileKey}/{name}?node-id={nodeId}
        https://www.figma.com/file/{fileKey}/{name}?node-id={nodeId}
        https://www.figma.com/design/{fileKey}?node-id={nodeId}

    Node ID format: URL uses '16650-538', API uses '16650:538'.

    Returns:
        (file_key, node_id) tuple

    Raises:
        HTTPException if URL format is invalid
    """
    # Match file key from path: /design/{key}/ or /file/{key}/
    path_match = re.search(r"figma\.com/(?:design|file)/([a-zA-Z0-9]+)", url)
    if not path_match:
        raise HTTPException(
            status_code=400,
            detail=(
                "Invalid Figma URL. Expected format: "
                "https://www.figma.com/design/{fileKey}/...?node-id={nodeId}"
            ),
        )
    file_key = path_match.group(1)

    # Extract node-id from query params
    node_match = re.search(r"[?&]node-id=([^&#]+)", url)
    if not node_match:
        raise HTTPException(
            status_code=400,
            detail="Figma URL must include a node-id parameter.",
        )

    # Decode percent-encoding (e.g. %3A → :) then convert dashes to colons
    raw_node_id = unquote(node_match.group(1))
    node_id = raw_node_id.replace("-", ":")

    return file_key, node_id


def _parse_figma_url_file_key(url: str) -> tuple:
    """Parse a Figma URL into (file_key, node_id_or_none).

    Like _parse_figma_url but does not require node-id parameter.
    Used when selected_screens provides node IDs explicitly.

    Returns:
        (file_key, node_id or None)
    """
    path_match = re.search(r"figma\.com/(?:design|file)/([a-zA-Z0-9]+)", url)
    if not path_match:
        raise HTTPException(
            status_code=400,
            detail=(
                "Invalid Figma URL. Expected format: "
                "https://www.figma.com/design/{fileKey}/..."
            ),
        )
    file_key = path_match.group(1)

    # node-id is optional in this variant
    node_match = re.search(r"[?&]node-id=([^&#]+)", url)
    node_id = None
    if node_match:
        raw_node_id = unquote(node_match.group(1))
        node_id = raw_node_id.replace("-", ":")

    return file_key, node_id


# --- Pipeline Execution ---


def _on_pipeline_task_done(task: asyncio.Task, job_id: str) -> None:
    """Callback for pipeline background tasks — logs unhandled exceptions."""
    if task.cancelled():
        logger.warning(f"Job {job_id}: Pipeline task was cancelled")
        return
    exc = task.exception()
    if exc:
        logger.error(
            f"Job {job_id}: Pipeline task raised unhandled exception: {exc}",
            exc_info=exc,
        )


async def _execute_design_pipeline(job_id: str):
    """Execute the design-to-code pipeline as a background task.

    Loads the design_to_code template, builds the LangGraph,
    and runs it with SSE event streaming.

    Uses get_session_ctx() for DB access since this runs outside
    FastAPI's request lifecycle.
    """
    # Read job from DB
    async with get_session_ctx() as session:
        repo = DesignJobRepository(session)
        job = await repo.get(job_id)
        if not job:
            logger.error(f"Job {job_id}: Not found in DB")
            return
        # Snapshot needed fields before session closes
        design_file = job.design_file
        output_dir = job.output_dir
        cwd = job.cwd
        max_retries = job.max_retries

    # Track final state for job_done event
    final_status = "failed"
    final_error: Optional[str] = None
    components_total = 0
    components_completed = 0
    components_failed = 0

    try:
        # Update status to running
        async with get_session_ctx() as session:
            repo = DesignJobRepository(session)
            await repo.update_status(job_id, "running")
        push_node_event(job_id, "job_status", {"status": "running"})

        # Load template and build workflow
        from workflow.templates import load_template, template_to_workflow_definition
        from workflow.engine.graph_builder import WorkflowDefinition
        from workflow.engine.executor import execute_dynamic_workflow

        template = load_template("design_to_code")
        workflow_dict = template_to_workflow_definition(template)
        workflow_def = WorkflowDefinition(**workflow_dict)

        # Read design file and extract components
        with open(design_file, "r", encoding="utf-8") as f:
            design_data = json.load(f)

        components = design_data.get("components", [])
        design_tokens = design_data.get("design_tokens", {})

        # Build summary strings for LLM prompts
        components_summary = "\n".join(
            f"- {c['name']} ({c.get('type', 'unknown')}): "
            f"{c.get('bounds', {}).get('width', '?')}x{c.get('bounds', {}).get('height', '?')}px"
            f" — {c.get('notes', '')}"
            for c in components
        )
        design_tokens_summary = json.dumps(design_tokens, ensure_ascii=False, indent=2)

        # Update job with component count
        components_total = len(components)
        async with get_session_ctx() as session:
            repo = DesignJobRepository(session)
            await repo.update_component_counts(job_id, total=components_total)

        # Enrich each component dict with a properties_summary field
        # so the template can reference {current_component.properties_summary}
        for c in components:
            props = []
            if c.get("bounds"):
                b = c["bounds"]
                props.append(f"位置: ({b.get('x', 0)}, {b.get('y', 0)})")
                props.append(f"尺寸: {b.get('width', '?')}x{b.get('height', '?')}px")
            if c.get("children_summary"):
                children_str = ", ".join(
                    f"{ch.get('name', '?')}({ch.get('type', '?')})"
                    for ch in c["children_summary"]
                )
                props.append(f"子元素: {children_str}")
            if c.get("text_content"):
                props.append(f"文字: {c['text_content']}")
            if c.get("notes"):
                props.append(f"备注: {c['notes']}")
            c["properties_summary"] = "\n".join(props) if props else "无详细属性"

        # Build initial state from design file
        # NOTE: All fields referenced in template prompts MUST exist here,
        # because graph_builder only merges node outputs for keys already in state.
        initial_state = {
            "design_file": design_file,
            "output_dir": output_dir,
            "cwd": cwd,
            "max_retries": max_retries,
            "job_id": job_id,
            # Design data
            "components": components,
            "components_count": len(components),
            "design_tokens": design_tokens,
            "components_summary": components_summary,
            "design_tokens_summary": design_tokens_summary,
            # CSS variable names for LLM prompt injection — ensures generated
            # components reference canonical variable names instead of inventing
            # their own (e.g. --color-brand-primary, not --brand-primary).
            "variables_css_content": _generate_variables_css(design_tokens),
            # Interaction notes from /scan-figma (Sprint 3)
            "interaction_notes": design_data.get("interaction_notes", []),
            "interaction_notes_summary": _build_interaction_notes_summary(
                design_data.get("interaction_notes", [])
            ),
            # QA checklist from /scan-figma (Sprint 3)
            "qa_checklist": design_data.get("qa_checklist", []),
            # Template variable placeholders — needed for state merge propagation
            "skeleton_code": "",
            "component_registry_summary": "暂无已完成组件",
            "neighbor_code": "暂无相邻组件代码",
            "failed_components": "暂无",
            # Initial state for the pipeline
            "component_registry": {"components": []},
            "current_index": 0,
            "retry_count": 0,
            "context": {},
            "results": [],
            "config": {
                "css_framework": "tailwind",
                "max_retries": max_retries,
                "smoke_test_count": 3,
            },
        }

        logger.info(f"Job {job_id}: Starting pipeline execution")

        # Execute the workflow with SSE tracking
        result = await execute_dynamic_workflow(
            workflow_def=workflow_def,
            initial_state=initial_state,
            run_id=job_id,
        )

        # Determine final status
        final_status = "completed" if result.get("success") else "failed"
        final_error = result.get("error")
        result_summary = _extract_result_summary(result)

        # Extract component counts from result.
        # The accumulated registry is inside output_node (LangGraph internal state),
        # not at the top level of the executor's result dict.
        output_node = result.get("output_node", {})
        registry = (
            output_node.get("component_registry")
            or result.get("component_registry")
            or {}
        )
        if isinstance(registry, dict):
            reg_components = registry.get("components", [])
            if reg_components:
                components_total = len(reg_components)
                components_completed = sum(
                    1 for c in reg_components if c.get("status") == "completed"
                )
                components_failed = sum(
                    1 for c in reg_components if c.get("status") == "failed"
                )

        # Persist final state to DB
        async with get_session_ctx() as session:
            repo = DesignJobRepository(session)
            await repo.update(
                job_id,
                status=final_status,
                completed_at=datetime.now(timezone.utc),
                error=final_error,
                result=result_summary,
                components_total=components_total,
                components_completed=components_completed,
                components_failed=components_failed,
            )

        # Write generated code to disk
        _write_generated_code(result, output_dir, job_id)

        logger.info(
            f"Job {job_id}: Pipeline {final_status} — "
            f"{components_completed}/{components_total} components"
        )

    except Exception as e:
        logger.error(f"Job {job_id}: Pipeline execution failed: {e}", exc_info=True)
        final_status = "failed"
        final_error = str(e)
        async with get_session_ctx() as session:
            repo = DesignJobRepository(session)
            await repo.update_status(
                job_id, "failed",
                error=str(e),
                completed_at=datetime.now(timezone.utc),
            )

    # Always push final job_done event
    push_node_event(job_id, "job_done", {
        "status": final_status,
        "components_total": components_total,
        "components_completed": components_completed,
        "components_failed": components_failed,
        "error": final_error,
    })


async def _execute_figma_pipeline(
    job_id: str,
    file_key: str,
    node_id: str,
    interaction_note_ids: Optional[List[str]] = None,
):
    """Execute the Figma → design-to-code pipeline.

    Phase 1: Fetch design data from Figma REST API (node tree + screenshots)
    Phase 1.5: Extract interaction notes (if IDs provided from /scan-figma)
    Phase 2: Run the standard design-to-code pipeline on the generated export

    Uses get_session_ctx() for DB access since this runs outside
    FastAPI's request lifecycle.
    """
    # Read job from DB
    async with get_session_ctx() as session:
        repo = DesignJobRepository(session)
        job = await repo.get(job_id)
        if not job:
            logger.error(f"Job {job_id}: Not found in DB")
            return
        output_dir = job.output_dir

    final_status = "failed"
    final_error: Optional[str] = None
    components_total = 0
    components_completed = 0
    components_failed = 0

    try:
        # Phase 1: Fetch from Figma
        async with get_session_ctx() as session:
            repo = DesignJobRepository(session)
            await repo.update_status(job_id, "running")
        push_node_event(job_id, "job_status", {"status": "running"})
        push_node_event(job_id, "figma_fetch_start", {
            "file_key": file_key,
            "node_id": node_id,
        })

        from workflow.integrations.figma_client import FigmaClient, FigmaClientError

        try:
            client = FigmaClient()
        except FigmaClientError as e:
            # Missing/invalid token — fail the job with a clear error
            error_msg = (
                "Figma API not configured. Set FIGMA_TOKEN environment variable "
                "with a valid Figma Personal Access Token "
                "(https://www.figma.com/developers/api#access-tokens)."
            )
            logger.error(f"Job {job_id}: {error_msg}")
            async with get_session_ctx() as session:
                repo = DesignJobRepository(session)
                await repo.update_status(
                    job_id, "failed",
                    error=error_msg,
                    completed_at=datetime.now(timezone.utc),
                )
            push_node_event(job_id, "job_done", {
                "status": "failed",
                "error": error_msg,
                "components_total": 0,
                "components_completed": 0,
                "components_failed": 0,
            })
            return

        try:
            export = await client.generate_design_export(
                file_key=file_key,
                page_node_id=node_id,
                output_dir=output_dir,
            )
        finally:
            await client.close()

        design_export_path = os.path.join(output_dir, "design_export.json")
        logger.info(
            f"Job {job_id}: Figma fetch complete — "
            f"{len(export.get('components', []))} components, "
            f"export written to {design_export_path}"
        )

        push_node_event(job_id, "figma_fetch_complete", {
            "components_count": len(export.get("components", [])),
            "design_export_path": design_export_path,
        })

        # Phase 1.5: Extract interaction notes if IDs provided
        if interaction_note_ids:
            try:
                # Re-open client for interaction note extraction
                note_client = FigmaClient()
                try:
                    interaction_notes = await note_client.extract_interaction_contexts(
                        file_key=file_key,
                        node_ids=interaction_note_ids,
                        output_dir=output_dir,
                    )
                finally:
                    await note_client.close()

                # Inject into the export and re-write
                export["interaction_notes"] = interaction_notes
                with open(design_export_path, "w", encoding="utf-8") as f:
                    json.dump(export, f, ensure_ascii=False, indent=2)
                logger.info(
                    f"Job {job_id}: Extracted {len(interaction_notes)} interaction notes"
                )
            except Exception as e:
                # Non-fatal: interaction notes are supplementary
                logger.warning(
                    f"Job {job_id}: Failed to extract interaction notes: {e}"
                )

        # Update design_file in DB to point to the generated export
        async with get_session_ctx() as session:
            repo = DesignJobRepository(session)
            await repo.update(job_id, design_file=design_export_path)

        # Phase 2: Run the standard pipeline (reuse _execute_design_pipeline logic)
        # The design_export.json is now on disk, so we run the normal pipeline
        await _execute_design_pipeline(job_id)
        return  # _execute_design_pipeline handles its own DB updates + job_done event

    except Exception as e:
        logger.error(f"Job {job_id}: Figma pipeline failed: {e}", exc_info=True)
        final_status = "failed"
        final_error = str(e)
        async with get_session_ctx() as session:
            repo = DesignJobRepository(session)
            await repo.update_status(
                job_id, "failed",
                error=str(e),
                completed_at=datetime.now(timezone.utc),
            )

        # Push final job_done event (only if we didn't get to _execute_design_pipeline)
        push_node_event(job_id, "job_done", {
            "status": final_status,
            "components_total": components_total,
            "components_completed": components_completed,
            "components_failed": components_failed,
            "error": final_error,
        })


async def _execute_spec_pipeline(
    job_id: str,
    file_key: str,
    node_id: str,
    output_dir: str,
    model: Optional[str] = None,
):
    """Execute the 3-node spec pipeline as a background task.

    Phase 1: Fetch raw Figma data (node tree + screenshots + variables)
    Phase 2: FrameDecomposerNode — structural extraction (70%)
    Phase 3: SpecAnalyzerNode — LLM vision analysis (30%)
    Phase 4: SpecAssemblerNode — final spec assembly

    Uses get_session_ctx() for DB access since this runs outside
    FastAPI's request lifecycle.
    """
    final_status = "failed"
    final_error: Optional[str] = None
    components_total = 0
    components_completed = 0
    components_failed = 0

    try:
        # Update status to running
        async with get_session_ctx() as session:
            repo = DesignJobRepository(session)
            await repo.update_status(job_id, "running")
        push_node_event(job_id, "job_status", {"status": "running"})

        # Phase 1: Fetch from Figma
        push_node_event(job_id, "figma_fetch_start", {
            "file_key": file_key,
            "node_id": node_id,
        })

        from workflow.integrations.figma_client import FigmaClient, FigmaClientError

        try:
            client = FigmaClient()
        except FigmaClientError as e:
            error_msg = (
                "Figma API not configured. Set FIGMA_TOKEN environment variable "
                "with a valid Figma Personal Access Token."
            )
            logger.error(f"Job {job_id}: {error_msg}")
            async with get_session_ctx() as session:
                repo = DesignJobRepository(session)
                await repo.update_status(
                    job_id, "failed",
                    error=error_msg,
                    completed_at=datetime.now(timezone.utc),
                )
            push_node_event(job_id, "job_done", {
                "status": "failed", "error": error_msg,
                "components_total": 0, "components_completed": 0,
                "components_failed": 0,
            })
            return

        try:
            # 1a. Fetch raw node tree
            nodes_resp = await client.get_file_nodes(file_key, [node_id])
            file_name = nodes_resp.get("name", "")
            nodes_data = nodes_resp.get("nodes", {})
            page_data = nodes_data.get(node_id, {})
            page_doc = page_data.get("document", {})
            page_name = page_doc.get("name", "")

            # Skip resolve_to_page — user targets the exact Frame they want.
            # The scan-figma endpoint still uses resolve_to_page for discovery.

            # 1b. Collect top-level children IDs for screenshots
            children = page_doc.get("children", [])
            child_node_ids = [c.get("id") for c in children if c.get("id")]
            # Also include the page node itself
            all_screenshot_ids = [node_id] + child_node_ids

            # 1c. Download screenshots
            screenshot_paths: Dict[str, str] = {}
            if all_screenshot_ids:
                try:
                    screenshot_paths = await client.download_screenshots(
                        file_key, all_screenshot_ids, output_dir,
                    )
                except FigmaClientError as e:
                    logger.warning(f"Job {job_id}: Screenshot download failed: {e}")

            # 1d. Fetch design tokens from variables
            design_tokens_raw: Dict[str, Any] = {}
            try:
                design_tokens_raw = await client.get_design_tokens(file_key)
            except FigmaClientError as e:
                logger.warning(f"Job {job_id}: Design tokens fetch failed: {e}")
        finally:
            await client.close()

        push_node_event(job_id, "figma_fetch_complete", {
            "components_count": len(children),
            "screenshots_count": len(screenshot_paths),
        })

        logger.info(
            f"Job {job_id}: Figma fetch complete — "
            f"{len(children)} children, {len(screenshot_paths)} screenshots"
        )

        # Phase 2: FrameDecomposerNode
        from workflow.nodes.spec_nodes import FrameDecomposerNode

        decomposer = FrameDecomposerNode(
            node_id="frame_decomposer_0",
            node_type="frame_decomposer",
            config={},
        )
        decomposer_result = await decomposer.execute({
            "figma_node_tree": nodes_resp,
            "design_tokens": design_tokens_raw,
            "page_name": page_name,
            "page_node_id": node_id,
            "file_key": file_key,
            "file_name": file_name,
            "screenshot_paths": screenshot_paths,
        })

        components = decomposer_result.get("components", [])
        page_meta = decomposer_result.get("page", {})
        schema_tokens = decomposer_result.get("design_tokens", {})
        source_meta = decomposer_result.get("source", {})
        components_total = len(components)

        # Update component count in DB
        async with get_session_ctx() as session:
            repo = DesignJobRepository(session)
            await repo.update_component_counts(job_id, total=components_total)

        push_node_event(job_id, "frame_decomposed", {
            "components_count": components_total,
            "page": page_meta,
            "components": components,
        })

        logger.info(
            f"Job {job_id}: FrameDecomposer complete — "
            f"{components_total} components"
        )

        # Phase 3: SpecAnalyzerNode
        from workflow.nodes.spec_nodes import SpecAnalyzerNode

        analyzer = SpecAnalyzerNode(
            node_id="spec_analyzer_0",
            node_type="spec_analyzer",
            config={
                "cwd": output_dir,
                "model": model or "",
                "max_tokens": 4096,
            },
        )
        analyzer_result = await analyzer.execute({
            "components": components,
            "page": page_meta,
            "design_tokens": schema_tokens,
            "source": source_meta,
            "run_id": job_id,
        })

        analyzed_components = analyzer_result.get("components", components)
        analysis_stats = analyzer_result.get("analysis_stats", {})
        components_completed = analysis_stats.get("succeeded", 0)
        components_failed = analysis_stats.get("failed", 0)

        # Surface SpecAnalyzer errors to the user via SSE
        analyzer_error = analysis_stats.get("error")
        if analyzer_error:
            # Make the error message user-friendly
            if "api_key" in str(analyzer_error).lower() or "auth" in str(analyzer_error).lower():
                friendly_msg = "语义分析未执行：请检查 ANTHROPIC_API_KEY 环境变量配置"
            else:
                friendly_msg = f"语义分析失败：{analyzer_error}"
            logger.warning(
                f"Job {job_id}: SpecAnalyzer error — {analyzer_error}"
            )
            push_node_event(job_id, "workflow_error", {
                "message": friendly_msg,
                "node_id": "spec_analyzer_0",
                "error": str(analyzer_error),
            })
            # Mark all components as failed if none succeeded
            if components_completed == 0:
                components_failed = components_total
        else:
            # Edge case: client init OK but every component analysis failed
            if components_completed == 0 and components_total > 0:
                push_node_event(job_id, "workflow_error", {
                    "message": f"语义分析全部失败：{components_total} 个组件均未成功",
                    "node_id": "spec_analyzer_0",
                })
                components_failed = components_total
            logger.info(
                f"Job {job_id}: SpecAnalyzer complete — "
                f"{components_completed}/{components_total} succeeded"
            )

        # Phase 4: SpecAssemblerNode
        from workflow.nodes.spec_nodes import SpecAssemblerNode

        assembler = SpecAssemblerNode(
            node_id="spec_assembler_0",
            node_type="spec_assembler",
            config={"output_dir": output_dir},
        )
        assembler_result = await assembler.execute({
            "components": analyzed_components,
            "page": page_meta,
            "design_tokens": schema_tokens,
            "source": source_meta,
            "output_dir": output_dir,
        })

        spec_path = assembler_result.get("spec_path", "")
        spec_document = assembler_result.get("spec_document", {})

        push_node_event(job_id, "spec_complete", {
            "spec_path": spec_path,
            "components_count": components_total,
            "components_succeeded": components_completed,
            "components_failed": components_failed,
        })

        final_status = "completed"

        # Persist final state to DB
        async with get_session_ctx() as session:
            repo = DesignJobRepository(session)
            await repo.update(
                job_id,
                status=final_status,
                design_file=spec_path,
                completed_at=datetime.now(timezone.utc),
                result={
                    "spec_path": spec_path,
                    "analysis_stats": analysis_stats,
                    "components_count": components_total,
                },
                components_total=components_total,
                components_completed=components_completed,
                components_failed=components_failed,
            )

        logger.info(
            f"Job {job_id}: Spec pipeline {final_status} — "
            f"{components_completed}/{components_total} components, "
            f"spec at {spec_path}"
        )

    except Exception as e:
        logger.error(f"Job {job_id}: Spec pipeline failed: {e}", exc_info=True)
        final_status = "failed"
        final_error = str(e)
        async with get_session_ctx() as session:
            repo = DesignJobRepository(session)
            await repo.update_status(
                job_id, "failed",
                error=str(e),
                completed_at=datetime.now(timezone.utc),
            )

    # Always push final job_done event
    push_node_event(job_id, "job_done", {
        "status": final_status,
        "components_total": components_total,
        "components_completed": components_completed,
        "components_failed": components_failed,
        "error": final_error,
    })


def _extract_result_summary(result: Dict[str, Any]) -> Dict[str, Any]:
    """Extract a summary from the full workflow result for API response."""
    summary = {}

    # Output node result
    output = result.get("output_node", {})
    if isinstance(output, dict):
        summary["output"] = {
            k: v for k, v in output.items()
            if k in ("job_id", "results", "components_count", "output_dir")
        }

    # Component registry — prefer output_node's accumulated version
    output_registry = output.get("component_registry") if isinstance(output, dict) else None
    registry = output_registry or result.get("component_registry", {})
    if isinstance(registry, dict):
        summary["component_registry"] = registry

    # Execution stats
    summary["node_execution_counts"] = result.get("node_execution_counts", {})
    summary["success"] = result.get("success", False)

    return summary


def _build_interaction_notes_summary(notes: List[Dict[str, Any]]) -> str:
    """Build a text summary of interaction notes for LLM prompt injection.

    Formats interaction notes into a readable string that can be
    referenced in template prompts via {interaction_notes_summary}.
    """
    if not notes:
        return "暂无交互说明"

    lines = []
    for note in notes:
        source = note.get("source_frame", note.get("name", "未知"))
        related = note.get("related_to", "")
        texts = note.get("text_content", [])
        if isinstance(texts, list):
            text_str = "; ".join(texts[:10])  # Cap at 10 items
        else:
            text_str = str(texts)

        header = f"[{source}]"
        if related:
            header += f" → 关联: {related}"
        lines.append(f"{header}: {text_str}")

    return "\n".join(lines)


def _generate_variables_css(design_tokens: Dict[str, Any]) -> str:
    """Generate a CSS file with custom properties from design tokens.

    Converts the design_tokens structure from design_export.json into
    CSS custom properties under :root, so generated components using
    var(--color-brand-primary) etc. render correctly in Sandpack preview.

    Also emits short-name aliases (e.g. --brand-primary) because LLM-generated
    components sometimes omit the category prefix.
    """
    lines = [":root {"]

    # Colors — canonical names + short aliases
    colors = design_tokens.get("colors", {})
    for name, value in colors.items():
        lines.append(f"  --color-{name}: {value};")
    # Short aliases so var(--brand-primary) also resolves
    for name, value in colors.items():
        lines.append(f"  --{name}: {value};")

    # Fonts
    fonts = design_tokens.get("fonts", {})
    if fonts.get("family"):
        lines.append(f"  --font-family: {fonts['family']}, -apple-system, sans-serif;")
    for weight_name, weight_value in fonts.get("weights", {}).items():
        lines.append(f"  --font-weight-{weight_name}: {weight_value};")

    # Spacing
    for name, value in design_tokens.get("spacing", {}).items():
        lines.append(f"  --spacing-{name}: {value};")

    # Border radius
    for name, value in design_tokens.get("radius", {}).items():
        lines.append(f"  --radius-{name}: {value};")

    lines.append("}")
    return "\n".join(lines) + "\n"


def _write_generated_code(result: Dict[str, Any], output_dir: str, job_id: str):
    """Extract generated code from pipeline result and write to disk.

    Parses LLM agent outputs for code blocks and writes them as files.
    - variables.css → CSS custom properties from design tokens
    - skeleton code → layout/PageSkeleton.tsx
    - component code → components/{Name}.tsx
    - assembled page → Page.tsx
    """
    written_files = []

    # 0. Write variables.css from design tokens
    design_tokens = result.get("design_tokens", {})
    if isinstance(design_tokens, dict) and design_tokens:
        css_content = _generate_variables_css(design_tokens)
        css_path = os.path.join(output_dir, "variables.css")
        with open(css_path, "w", encoding="utf-8") as f:
            f.write(css_content)
        written_files.append(css_path)
        logger.info(f"Job {job_id}: Wrote design tokens → {css_path}")

    # 1. Write skeleton code (prefer output_node's accumulated version)
    output_node = result.get("output_node", {})
    skeleton_code = (
        (output_node.get("skeleton_code") if isinstance(output_node, dict) else None)
        or result.get("skeleton_code")
        or ""
    )
    if skeleton_code and isinstance(skeleton_code, str) and len(skeleton_code) > 50:
        skeleton_content = _extract_code_block(skeleton_code)
        if skeleton_content:
            skeleton_path = os.path.join(output_dir, "layout", "PageSkeleton.tsx")
            os.makedirs(os.path.dirname(skeleton_path), exist_ok=True)
            with open(skeleton_path, "w", encoding="utf-8") as f:
                f.write(skeleton_content)
            written_files.append(skeleton_path)
            logger.info(f"Job {job_id}: Wrote skeleton → {skeleton_path}")

    # 2. Write component code from registry (prefer output_node's accumulated version)
    registry = (
        (output_node.get("component_registry") if isinstance(output_node, dict) else None)
        or result.get("component_registry")
        or {}
    )
    if isinstance(registry, dict):
        for comp in registry.get("components", []):
            name = comp.get("name", "Unknown")
            code = comp.get("code", "")
            if code and isinstance(code, str) and len(code) > 20:
                comp_content = _extract_code_block(code)
                if comp_content:
                    comp_path = os.path.join(output_dir, "components", f"{name}.tsx")
                    os.makedirs(os.path.dirname(comp_path), exist_ok=True)
                    with open(comp_path, "w", encoding="utf-8") as f:
                        f.write(comp_content)
                    written_files.append(comp_path)
                    logger.info(f"Job {job_id}: Wrote component → {comp_path}")

    # 3. Write assembled page
    assemble_output = result.get("assemble_page", {})
    if isinstance(assemble_output, dict):
        page_code = assemble_output.get("result", "")
    elif isinstance(assemble_output, str):
        page_code = assemble_output
    else:
        page_code = ""

    if page_code and isinstance(page_code, str) and len(page_code) > 50:
        page_content = _extract_code_block(page_code)
        if page_content:
            page_path = os.path.join(output_dir, "Page.tsx")
            with open(page_path, "w", encoding="utf-8") as f:
                f.write(page_content)
            written_files.append(page_path)
            logger.info(f"Job {job_id}: Wrote page → {page_path}")

    if written_files:
        logger.info(f"Job {job_id}: Wrote {len(written_files)} files to {output_dir}")
    else:
        logger.warning(f"Job {job_id}: No code files written — LLM output may be empty")


def _extract_code_block(text: str) -> str:
    """Extract the first code block from LLM output, or return raw text."""
    # Try to extract ```tsx or ```typescript code block
    pattern = r"```(?:tsx|typescript|jsx|ts|js)?\s*\n(.*?)```"
    match = re.search(pattern, text, re.DOTALL)
    if match:
        return match.group(1).strip()
    # If no code block found, return the text itself (might be raw code)
    return text.strip()
