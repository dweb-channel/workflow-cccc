"""Workspace API endpoints.

Provides CRUD for workspaces (1:1 mapping with repositories).
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from sqlalchemy.exc import IntegrityError

from app.database import get_session_ctx
from app.repositories.workspace import WorkspaceRepository, preflight_check

logger = logging.getLogger("workflow.routes.workspace")

router = APIRouter(prefix="/api/v2/workspaces", tags=["workspaces"])


# --- Schemas ---


class WorkspaceCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    repo_path: str = Field(..., min_length=1)
    config_defaults: Optional[Dict[str, Any]] = None


class WorkspaceUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    repo_path: Optional[str] = None
    config_defaults: Optional[Dict[str, Any]] = None


class WorkspaceResponse(BaseModel):
    id: str
    name: str
    repo_path: str
    config_defaults: Optional[Dict[str, Any]] = None
    job_count: int = 0
    created_at: str
    updated_at: str
    last_used_at: Optional[str] = None


class WorkspaceListResponse(BaseModel):
    workspaces: List[WorkspaceResponse]
    total: int
    page: int
    page_size: int


class PreflightResponse(BaseModel):
    ok: bool
    errors: List[str] = []
    warnings: List[str] = []


# --- Endpoints ---


@router.post("", status_code=201, response_model=WorkspaceResponse)
async def create_workspace(payload: WorkspaceCreate):
    """Create a new workspace. Validates repo_path via preflight."""
    # Preflight check (also canonicalizes path)
    check = preflight_check(payload.repo_path)
    if not check["ok"]:
        raise HTTPException(
            status_code=400,
            detail=f"Preflight failed: {'; '.join(check['errors'])}",
        )
    canonical_path = check.get("canonical_path", payload.repo_path)

    async with get_session_ctx() as session:
        repo = WorkspaceRepository(session)

        # Check uniqueness against canonical path
        existing = await repo.get_by_repo_path(canonical_path)
        if existing:
            raise HTTPException(
                status_code=409,
                detail=f"Workspace already exists for repo_path: {canonical_path} (id={existing.id})",
            )

        try:
            ws = await repo.create(
                name=payload.name,
                repo_path=canonical_path,
                config_defaults=payload.config_defaults,
            )
        except IntegrityError:
            raise HTTPException(status_code=409, detail=f"该仓库路径已被其他项目组使用: {canonical_path}")
        logger.info(f"Workspace created: {ws.id} ({ws.name}) -> {ws.repo_path}")
        return _ws_to_response(ws, job_count=0)


@router.get("", response_model=WorkspaceListResponse)
async def list_workspaces(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
):
    """List all workspaces, ordered by last_used_at desc."""
    async with get_session_ctx() as session:
        repo = WorkspaceRepository(session)
        workspaces, total = await repo.list(page=page, page_size=page_size)
        return WorkspaceListResponse(
            workspaces=[_ws_to_response(ws) for ws in workspaces],
            total=total,
            page=page,
            page_size=page_size,
        )


@router.get("/{workspace_id}", response_model=WorkspaceResponse)
async def get_workspace(workspace_id: str):
    """Get a workspace by ID."""
    async with get_session_ctx() as session:
        repo = WorkspaceRepository(session)
        ws = await repo.get(workspace_id, load_jobs=True)
    if not ws:
        raise HTTPException(status_code=404, detail=f"Workspace '{workspace_id}' not found")
    return _ws_to_response(ws)


@router.put("/{workspace_id}", response_model=WorkspaceResponse)
async def update_workspace(workspace_id: str, payload: WorkspaceUpdate):
    """Update a workspace."""
    # If repo_path is being changed, validate and canonicalize it
    canonical_path = None
    if payload.repo_path is not None:
        check = preflight_check(payload.repo_path)
        if not check["ok"]:
            raise HTTPException(
                status_code=400,
                detail=f"Preflight failed: {'; '.join(check['errors'])}",
            )
        canonical_path = check.get("canonical_path", payload.repo_path)

    async with get_session_ctx() as session:
        repo = WorkspaceRepository(session)

        # Check uniqueness if repo_path is changing
        if canonical_path is not None:
            existing = await repo.get_by_repo_path(canonical_path)
            if existing and existing.id != workspace_id:
                raise HTTPException(
                    status_code=409,
                    detail=f"Workspace already exists for repo_path: {canonical_path}",
                )

        ws = await repo.update(
            workspace_id=workspace_id,
            name=payload.name,
            repo_path=canonical_path,
            config_defaults=payload.config_defaults,
        )
        if not ws:
            raise HTTPException(status_code=404, detail=f"Workspace '{workspace_id}' not found")
        # Reload with jobs eagerly loaded (avoid MissingGreenlet on lazy load)
        ws = await repo.get(workspace_id, load_jobs=True)
        logger.info(f"Workspace updated: {ws.id}")
        return _ws_to_response(ws)


@router.delete("/{workspace_id}", status_code=200)
async def delete_workspace(workspace_id: str):
    """Delete a workspace. Associated jobs are preserved (workspace_id set to NULL)."""
    async with get_session_ctx() as session:
        repo = WorkspaceRepository(session)
        deleted = await repo.delete(workspace_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Workspace '{workspace_id}' not found")
    logger.info(f"Workspace deleted: {workspace_id}")
    return {"success": True}


@router.post("/preflight", response_model=PreflightResponse)
async def workspace_preflight(payload: WorkspaceCreate):
    """Run preflight validation on a repo path without creating a workspace."""
    check = preflight_check(payload.repo_path)
    return PreflightResponse(**check)


# --- Helpers ---


def _ws_to_response(ws, job_count: Optional[int] = None) -> WorkspaceResponse:
    return WorkspaceResponse(
        id=ws.id,
        name=ws.name,
        repo_path=ws.repo_path,
        config_defaults=ws.config_defaults,
        job_count=job_count if job_count is not None else (len(ws.jobs) if hasattr(ws, 'jobs') and ws.jobs is not None else 0),
        created_at=ws.created_at.isoformat() if ws.created_at else "",
        updated_at=ws.updated_at.isoformat() if ws.updated_at else "",
        last_used_at=ws.last_used_at.isoformat() if ws.last_used_at else None,
    )
