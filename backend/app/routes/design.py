"""Design-to-Spec API endpoints.

Provides endpoints for running the spec analysis pipeline that converts
Figma designs into structured design_spec.json files.

Execution is async (background task) with SSE progress streaming.
No Temporal dependency — uses asyncio for POC validation.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import unquote

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session, get_session_ctx
from app.models.db import DesignJobModel
from app.repositories.design_job import DesignJobRepository
from app.sse import push_node_event, sse_event_generator

logger = logging.getLogger("workflow.routes.design")

router = APIRouter(prefix="/api/v2/design", tags=["design"])


# --- Schemas ---


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


@router.post("/scan-figma", response_model=FigmaScanResponse)
async def scan_figma_page(payload: FigmaScanRequest):
    """Scan a Figma page and classify frames into UI screens, interaction specs, etc.

    Synchronous endpoint — returns classification results for user confirmation
    before starting the pipeline. Does not create a job.

    Flow: scan-figma → user confirms → run-spec

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

    # Create job ID first, then isolate output under job-specific subdirectory
    job_id = f"spec_{uuid.uuid4().hex[:12]}"
    base_dir = os.path.abspath(payload.output_dir)
    output_dir = os.path.join(base_dir, job_id)
    os.makedirs(output_dir, exist_ok=True)

    # Create job in DB
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


# Allowed image extensions for screenshot serving
_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}


@router.get("/{job_id}/screenshots/{filename}")
async def get_screenshot(
    job_id: str,
    filename: str,
    session: AsyncSession = Depends(get_session),
):
    """Serve a component screenshot image for a design job.

    Screenshots are downloaded from Figma during pipeline execution and stored
    at {output_dir}/screenshots/{node_id}.png.

    Security: filename is validated to prevent path traversal — only bare
    filenames with image extensions are allowed (no slashes, no '..').

    Usage:
        GET /api/v2/design/{job_id}/screenshots/16650_539.png
        → PNG image response
    """
    # Path traversal protection: reject any path separators or '..'
    if ".." in filename or "/" in filename or "\\" in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")

    # Only serve image files
    ext = os.path.splitext(filename)[1].lower()
    if ext not in _IMAGE_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"Unsupported file type: {ext}")

    repo = DesignJobRepository(session)
    job = await repo.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")

    screenshot_path = os.path.join(job.output_dir, "screenshots", filename)

    if not os.path.isfile(screenshot_path):
        raise HTTPException(status_code=404, detail=f"Screenshot not found: {filename}")

    # Content-type mapping
    media_types = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
    }

    return FileResponse(
        screenshot_path,
        media_type=media_types.get(ext, "image/png"),
        headers={"Cache-Control": "no-cache"},
    )



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
    figma_last_modified = ""
    token_usage: Dict[str, int] = {}

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
            figma_last_modified = nodes_resp.get("lastModified", "")
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
                "max_retries": 2,
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
        token_usage = analyzer_result.get("token_usage", {})
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
            "token_usage": token_usage,
            "figma_last_modified": figma_last_modified,
        })

        spec_path = assembler_result.get("spec_path", "")
        spec_document = assembler_result.get("spec_document", {})
        validation = assembler_result.get("validation", {})

        push_node_event(job_id, "spec_complete", {
            "spec_path": spec_path,
            "components_count": components_total,
            "components_succeeded": components_completed,
            "components_failed": components_failed,
            "validation": validation,
            "token_usage": token_usage,
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
                    "validation": validation,
                    "token_usage": token_usage,
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

    except BaseException as e:
        logger.error(f"Job {job_id}: Spec pipeline failed: {e}", exc_info=True)
        final_status = "failed"
        final_error = str(e)
        try:
            async with get_session_ctx() as session:
                repo = DesignJobRepository(session)
                await repo.update_status(
                    job_id, "failed",
                    error=str(e),
                    completed_at=datetime.now(timezone.utc),
                )
        except Exception:
            logger.warning(f"Job {job_id}: Failed to persist error status to DB")
    finally:
        # Ensure DB is never stuck in "running" state
        if final_status not in ("completed", "failed"):
            final_status = "failed"
            final_error = final_error or "Pipeline interrupted unexpectedly"
            try:
                async with get_session_ctx() as session:
                    repo = DesignJobRepository(session)
                    await repo.update_status(
                        job_id, "failed",
                        error=final_error,
                        completed_at=datetime.now(timezone.utc),
                    )
            except Exception:
                pass  # DB may be unavailable during shutdown

        # Always push final job_done event
        push_node_event(job_id, "job_done", {
            "status": final_status,
            "components_total": components_total,
            "components_completed": components_completed,
            "components_failed": components_failed,
            "error": final_error,
        })




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


