"""Temporal Activity for Design-to-Spec Pipeline.

Single long-running activity that executes all 4 phases:
  1. Figma data fetch
  2. FrameDecomposer
  3. SpecAnalyzer (LLM vision)
  4. SpecAssembler

Migrated from app/routes/design.py _execute_spec_pipeline().
SSE events are pushed via HTTP POST (workflow/sse.py) since this
runs in a separate Temporal Worker process.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from temporalio import activity

from ..settings import (
    SPEC_ANALYZER_MAX_RETRIES,
    SPEC_ANALYZER_MAX_TOKENS,
    SPEC_HEARTBEAT_INTERVAL,
)

logger = logging.getLogger(__name__)


# SSE push helper — shared with batch_activities via sse_events module
from .sse_events import _push_event  # noqa: F401


# ---------------------------------------------------------------------------
# DB helpers (same pattern as batch_activities.py)
# ---------------------------------------------------------------------------

async def _update_job_status(
    job_id: str,
    status: str,
    error: Optional[str] = None,
    completed_at: Optional[datetime] = None,
    **extra: Any,
) -> bool:
    """Update design job status in DB."""
    try:
        from app.database import get_session_ctx
        from app.repositories.design_job import DesignJobRepository
        async with get_session_ctx() as session:
            repo = DesignJobRepository(session)
            kwargs: Dict[str, Any] = {"status": status}
            if error is not None:
                kwargs["error"] = error
            if completed_at is not None:
                kwargs["completed_at"] = completed_at
            kwargs.update(extra)
            await repo.update(job_id, **kwargs)
        return True
    except Exception as e:
        logger.error("DB update failed for %s: %s", job_id, e)
        return False


async def _update_component_counts(
    job_id: str,
    total: Optional[int] = None,
    completed: Optional[int] = None,
    failed: Optional[int] = None,
) -> bool:
    """Update component progress counters."""
    try:
        from app.database import get_session_ctx
        from app.repositories.design_job import DesignJobRepository
        async with get_session_ctx() as session:
            repo = DesignJobRepository(session)
            await repo.update_component_counts(
                job_id, total=total, completed=completed, failed=failed,
            )
        return True
    except Exception as e:
        logger.error("DB component count update failed for %s: %s", job_id, e)
        return False


# ---------------------------------------------------------------------------
# Checkpoint helpers (component-level resume on retry)
# ---------------------------------------------------------------------------

def _checkpoint_dir(output_dir: str) -> str:
    """Return the checkpoint directory path for this job."""
    return os.path.join(output_dir, ".spec_checkpoints")


def _save_checkpoint(output_dir: str, component_id: str, data: dict) -> None:
    """Save a completed component's analysis result as a checkpoint file."""
    cp_dir = _checkpoint_dir(output_dir)
    os.makedirs(cp_dir, exist_ok=True)
    safe_id = component_id.replace(":", "_").replace("/", "_")
    path = os.path.join(cp_dir, f"{safe_id}.json")
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
    except Exception as e:
        logger.warning("Failed to save checkpoint for %s: %s", component_id, e)


def _load_checkpoints(output_dir: str) -> Dict[str, dict]:
    """Load all component checkpoints from disk. Returns {component_id: data}."""
    cp_dir = _checkpoint_dir(output_dir)
    if not os.path.isdir(cp_dir):
        return {}
    result: Dict[str, dict] = {}
    try:
        for filename in os.listdir(cp_dir):
            if not filename.endswith(".json"):
                continue
            path = os.path.join(cp_dir, filename)
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            comp_id = data.get("id", "")
            if comp_id:
                result[comp_id] = data
    except Exception as e:
        logger.warning("Failed to load checkpoints from %s: %s", cp_dir, e)
    return result


# ---------------------------------------------------------------------------
# Periodic heartbeat (prevents Temporal timeout during long LLM calls)
# ---------------------------------------------------------------------------

async def _periodic_heartbeat(job_id: str, interval_seconds: float = 60.0) -> None:
    """Send periodic heartbeat to Temporal."""
    while True:
        await asyncio.sleep(interval_seconds)
        try:
            activity.heartbeat(f"keepalive:{job_id}")
        except Exception:
            break  # Activity cancelled or completed


# ---------------------------------------------------------------------------
# Main activity
# ---------------------------------------------------------------------------

@activity.defn
async def execute_spec_pipeline_activity(params: dict) -> dict:
    """Execute the full design-to-spec pipeline as a Temporal activity.

    Phases:
      1. Fetch Figma data (node tree, screenshots, design tokens)
      2. FrameDecomposer — structural extraction
      3. SpecAnalyzer — LLM vision analysis (two-pass)
      4. SpecAssembler — final spec assembly + validation

    Args:
        params: Dict with keys:
            - job_id: Unique job identifier
            - file_key: Figma file key
            - node_id: Figma page node ID
            - output_dir: Job output directory
            - model: Claude model override (optional)

    Returns:
        Dict with success status, spec_path, and stats.
    """
    job_id = params["job_id"]
    file_key = params["file_key"]
    node_id = params["node_id"]
    output_dir = params["output_dir"]
    model = params.get("model", "")

    final_status = "failed"
    final_error: Optional[str] = None
    components_total = 0
    components_completed = 0
    components_failed = 0
    figma_last_modified = ""
    token_usage: Dict[str, int] = {}

    # Start periodic heartbeat
    heartbeat_task = asyncio.create_task(
        _periodic_heartbeat(job_id, interval_seconds=SPEC_HEARTBEAT_INTERVAL)
    )

    try:
        # -- Update status to running --
        await _update_job_status(job_id, "running")
        await _push_event(job_id, "job_status", {"status": "running"})
        activity.heartbeat("phase:init")

        # ============================================================
        # Phase 1: Fetch from Figma
        # ============================================================
        await _push_event(job_id, "figma_fetch_start", {
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
            logger.error("Job %s: %s", job_id, error_msg)
            await _update_job_status(
                job_id, "failed", error=error_msg,
                completed_at=datetime.now(timezone.utc),
            )
            await _push_event(job_id, "job_done", {
                "status": "failed", "error": error_msg,
                "components_total": 0, "components_completed": 0,
                "components_failed": 0,
            })
            return {"success": False, "job_id": job_id, "error": error_msg}

        try:
            # 1a. Fetch raw node tree
            nodes_resp = await client.get_file_nodes(file_key, [node_id])
            file_name = nodes_resp.get("name", "")
            figma_last_modified = nodes_resp.get("lastModified", "")
            nodes_data = nodes_resp.get("nodes", {})
            page_data = nodes_data.get(node_id, {})
            page_doc = page_data.get("document", {})
            page_name = page_doc.get("name", "")

            # 1b. Collect top-level children IDs for screenshots
            children = page_doc.get("children", [])
            child_node_ids = [c.get("id") for c in children if c.get("id")]
            all_screenshot_ids = [node_id] + child_node_ids

            # 1c. Download screenshots
            screenshot_paths: Dict[str, str] = {}
            if all_screenshot_ids:
                try:
                    screenshot_paths = await client.download_screenshots(
                        file_key, all_screenshot_ids, output_dir,
                    )
                    # Warn about partially failed screenshots
                    failed_ids = [
                        nid for nid in all_screenshot_ids
                        if nid not in screenshot_paths
                    ]
                    if failed_ids:
                        await _push_event(job_id, "warning", {
                            "source": "figma_screenshots",
                            "message": f"{len(failed_ids)} 个组件截图下载失败",
                            "failed_node_ids": failed_ids,
                        })
                except FigmaClientError as e:
                    logger.warning("Job %s: Screenshot download failed: %s", job_id, e)
                    await _push_event(job_id, "warning", {
                        "source": "figma_screenshots",
                        "message": f"截图下载失败: {e}",
                    })

            # 1d. Fetch design tokens
            design_tokens_raw: Dict[str, Any] = {}
            try:
                design_tokens_raw = await client.get_design_tokens(file_key)
            except FigmaClientError as e:
                logger.warning("Job %s: Design tokens fetch failed: %s", job_id, e)
                await _push_event(job_id, "warning", {
                    "source": "figma_tokens",
                    "message": f"设计变量获取失败: {e}",
                })
        finally:
            await client.close()

        await _push_event(job_id, "figma_fetch_complete", {
            "components_count": len(children),
            "screenshots_count": len(screenshot_paths),
        })
        activity.heartbeat("phase:figma_fetch_done")

        logger.info(
            "Job %s: Figma fetch complete — %d children, %d screenshots",
            job_id, len(children), len(screenshot_paths),
        )

        # ============================================================
        # Phase 2: FrameDecomposerNode
        # ============================================================
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

        await _update_component_counts(job_id, total=components_total)

        await _push_event(job_id, "frame_decomposed", {
            "components_count": components_total,
            "page": page_meta,
            "components": components,
        })
        activity.heartbeat("phase:decompose_done")

        logger.info(
            "Job %s: FrameDecomposer complete — %d components",
            job_id, components_total,
        )

        # Fail fast if no components were found (T139)
        if components_total == 0:
            error_msg = (
                "未检测到任何组件。请检查 Figma 页面是否包含有效的 frame 节点，"
                "或确认 node_id 指向的节点有子元素。"
            )
            logger.error("Job %s: 0 components from FrameDecomposer — aborting", job_id)
            await _push_event(job_id, "workflow_error", {
                "message": error_msg,
                "node_id": "frame_decomposer_0",
            })
            await _update_job_status(
                job_id, "failed",
                error=error_msg,
                completed_at=datetime.now(timezone.utc),
            )
            await _push_event(job_id, "job_done", {
                "status": "failed",
                "error": error_msg,
                "components_total": 0,
                "components_completed": 0,
                "components_failed": 0,
            })
            return {
                "success": False,
                "job_id": job_id,
                "error": error_msg,
            }

        # ============================================================
        # Phase 3: SpecAnalyzerNode (LLM vision — slowest phase)
        # ============================================================
        from workflow.nodes.spec_nodes import SpecAnalyzerNode

        # -- Checkpoint resume: skip already-analyzed components --
        checkpoints = _load_checkpoints(output_dir)
        pre_completed: List[dict] = []
        pending_components: List[dict] = []
        pre_token_usage: Dict[str, int] = {}

        for comp in components:
            comp_id = comp.get("id", "")
            if comp_id in checkpoints:
                cp_data = checkpoints[comp_id]
                # Verify checkpoint has real analysis data (role != placeholder)
                if cp_data.get("role") and cp_data.get("role") != "other":
                    pre_completed.append(cp_data)
                    cp_tokens = cp_data.get("_token_usage", {})
                    pre_token_usage["input_tokens"] = (
                        pre_token_usage.get("input_tokens", 0)
                        + cp_tokens.get("input_tokens", 0)
                    )
                    pre_token_usage["output_tokens"] = (
                        pre_token_usage.get("output_tokens", 0)
                        + cp_tokens.get("output_tokens", 0)
                    )
                    continue
            pending_components.append(comp)

        if pre_completed:
            logger.info(
                "Job %s: Checkpoint resume — %d/%d from cache, %d pending",
                job_id, len(pre_completed), components_total, len(pending_components),
            )
            await _push_event(job_id, "checkpoint_resume", {
                "pre_completed": len(pre_completed),
                "pending": len(pending_components),
                "total": components_total,
            })

        # Run analyzer only for pending components
        analysis_stats: Dict[str, Any] = {}
        new_token_usage: Dict[str, int] = {}
        newly_analyzed: List[dict] = []

        if pending_components:
            analyzer = SpecAnalyzerNode(
                node_id="spec_analyzer_0",
                node_type="spec_analyzer",
                config={
                    "cwd": output_dir,
                    "model": model or "",
                    "max_tokens": SPEC_ANALYZER_MAX_TOKENS,
                    "max_retries": SPEC_ANALYZER_MAX_RETRIES,
                },
            )
            analyzer_result = await analyzer.execute({
                "components": pending_components,
                "page": page_meta,
                "design_tokens": schema_tokens,
                "source": source_meta,
                "run_id": job_id,
            })

            newly_analyzed = analyzer_result.get("components", pending_components)
            analysis_stats = analyzer_result.get("analysis_stats", {})
            new_token_usage = analyzer_result.get("token_usage", {})

            # Save checkpoints for newly succeeded components
            for comp in newly_analyzed:
                comp_id = comp.get("id", "")
                if comp_id and not comp.get("_analysis_failed"):
                    _save_checkpoint(output_dir, comp_id, comp)

        # Merge pre-completed (checkpoint) + newly analyzed
        analyzed_components = pre_completed + newly_analyzed

        # Aggregate counts
        new_completed = analysis_stats.get("succeeded", 0)
        new_failed = analysis_stats.get("failed", 0)
        components_completed = len(pre_completed) + new_completed
        components_failed = new_failed

        # Merge token usage
        token_usage = {
            "input_tokens": (
                pre_token_usage.get("input_tokens", 0)
                + new_token_usage.get("input_tokens", 0)
            ),
            "output_tokens": (
                pre_token_usage.get("output_tokens", 0)
                + new_token_usage.get("output_tokens", 0)
            ),
        }

        # Surface SpecAnalyzer errors (only for current run)
        analyzer_error = analysis_stats.get("error")
        if analyzer_error:
            if "api_key" in str(analyzer_error).lower() or "auth" in str(analyzer_error).lower():
                friendly_msg = "语义分析未执行：请检查 ANTHROPIC_API_KEY 环境变量配置"
            else:
                friendly_msg = f"语义分析失败：{analyzer_error}"
            logger.warning("Job %s: SpecAnalyzer error — %s", job_id, analyzer_error)
            await _push_event(job_id, "workflow_error", {
                "message": friendly_msg,
                "node_id": "spec_analyzer_0",
                "error": str(analyzer_error),
            })
            if components_completed == 0:
                components_failed = components_total
        else:
            if components_completed == 0 and components_total > 0:
                await _push_event(job_id, "workflow_error", {
                    "message": f"语义分析全部失败：{components_total} 个组件均未成功",
                    "node_id": "spec_analyzer_0",
                })
                components_failed = components_total
            logger.info(
                "Job %s: SpecAnalyzer complete — %d/%d succeeded (pre=%d, new=%d)",
                job_id, components_completed, components_total,
                len(pre_completed), new_completed,
            )

        activity.heartbeat(f"phase:analyze_done:{components_completed}/{components_total}")

        # ============================================================
        # Phase 4: SpecAssemblerNode
        # ============================================================
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
        validation = assembler_result.get("validation", {})

        await _push_event(job_id, "spec_complete", {
            "spec_path": spec_path,
            "components_count": components_total,
            "components_succeeded": components_completed,
            "components_failed": components_failed,
            "validation": validation,
            "token_usage": token_usage,
        })

        final_status = "completed"

        # Persist final state to DB
        await _update_job_status(
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

        activity.heartbeat("phase:complete")

        logger.info(
            "Job %s: Spec pipeline %s — %d/%d components, spec at %s",
            job_id, final_status, components_completed, components_total, spec_path,
        )

        return {
            "success": True,
            "job_id": job_id,
            "spec_path": spec_path,
            "components_total": components_total,
            "components_completed": components_completed,
            "components_failed": components_failed,
            "token_usage": token_usage,
        }

    except asyncio.CancelledError:
        # Temporal cancellation — clean up gracefully
        logger.info("Job %s: Pipeline cancelled by Temporal", job_id)
        await _update_job_status(
            job_id, "cancelled",
            completed_at=datetime.now(timezone.utc),
        )
        await _push_event(job_id, "job_done", {
            "status": "cancelled",
            "components_total": components_total,
            "components_completed": components_completed,
            "components_failed": components_failed,
        })
        return {"success": False, "job_id": job_id, "cancelled": True}

    except BaseException as e:
        logger.error("Job %s: Spec pipeline failed: %s", job_id, e, exc_info=True)
        final_status = "failed"
        final_error = str(e)
        await _update_job_status(
            job_id, "failed",
            error=final_error,
            completed_at=datetime.now(timezone.utc),
        )
        return {"success": False, "job_id": job_id, "error": final_error}

    finally:
        # Stop heartbeat
        heartbeat_task.cancel()
        try:
            await heartbeat_task
        except asyncio.CancelledError:
            pass

        # Ensure DB never stuck in "running"
        if final_status not in ("completed", "failed", "cancelled"):
            final_status = "failed"
            final_error = final_error or "Pipeline interrupted unexpectedly"
            await _update_job_status(
                job_id, "failed",
                error=final_error,
                completed_at=datetime.now(timezone.utc),
            )

        # Always push final job_done event
        if final_status != "cancelled":  # Cancelled already pushed above
            await _push_event(job_id, "job_done", {
                "status": final_status,
                "components_total": components_total,
                "components_completed": components_completed,
                "components_failed": components_failed,
                "error": final_error,
            })
