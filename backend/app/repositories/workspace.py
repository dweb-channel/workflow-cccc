"""Repository layer for workspace persistence.

Provides async CRUD operations for WorkspaceModel.
"""

from __future__ import annotations

import os
import subprocess
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.db import WorkspaceModel


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class WorkspaceRepository:
    """Data access layer for workspaces."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(
        self,
        name: str,
        repo_path: str,
        config_defaults: Optional[Dict[str, Any]] = None,
    ) -> WorkspaceModel:
        ws = WorkspaceModel(
            name=name,
            repo_path=repo_path,
            config_defaults=config_defaults,
        )
        self.session.add(ws)
        await self.session.flush()
        return ws

    async def get(self, workspace_id: str, load_jobs: bool = False) -> Optional[WorkspaceModel]:
        query = select(WorkspaceModel).where(WorkspaceModel.id == workspace_id)
        if load_jobs:
            query = query.options(selectinload(WorkspaceModel.jobs))
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def get_by_repo_path(self, repo_path: str) -> Optional[WorkspaceModel]:
        result = await self.session.execute(
            select(WorkspaceModel).where(WorkspaceModel.repo_path == repo_path)
        )
        return result.scalar_one_or_none()

    async def list(
        self,
        page: int = 1,
        page_size: int = 50,
    ) -> Tuple[List[WorkspaceModel], int]:
        query = (
            select(WorkspaceModel)
            .options(selectinload(WorkspaceModel.jobs))
            .order_by(WorkspaceModel.last_used_at.desc().nullslast(), WorkspaceModel.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        count_query = select(func.count()).select_from(WorkspaceModel)

        result = await self.session.execute(query)
        workspaces = list(result.scalars().all())

        count_result = await self.session.execute(count_query)
        total = count_result.scalar() or 0

        return workspaces, total

    async def update(
        self,
        workspace_id: str,
        name: Optional[str] = None,
        repo_path: Optional[str] = None,
        config_defaults: Optional[Dict[str, Any]] = None,
    ) -> Optional[WorkspaceModel]:
        ws = await self.get(workspace_id)
        if not ws:
            return None

        if name is not None:
            ws.name = name
        if repo_path is not None:
            ws.repo_path = repo_path
        if config_defaults is not None:
            ws.config_defaults = config_defaults
        ws.updated_at = _utcnow()

        await self.session.flush()
        return ws

    async def delete(self, workspace_id: str) -> bool:
        ws = await self.get(workspace_id)
        if not ws:
            return False
        await self.session.delete(ws)
        await self.session.flush()
        return True

    async def touch(self, workspace_id: str) -> None:
        """Update last_used_at timestamp."""
        ws = await self.get(workspace_id)
        if ws:
            ws.last_used_at = _utcnow()
            await self.session.flush()


def preflight_check(repo_path: str) -> Dict[str, Any]:
    """Validate a repo path for workspace creation.

    Checks:
    - Directory exists and is readable
    - Is a git repository
    - git CLI is available

    Returns:
        {"ok": True, "canonical_path": ...} or {"ok": False, "errors": [...], "warnings": [...]}
    """
    errors: List[str] = []
    warnings: List[str] = []

    # Canonicalize path (resolve symlinks, .., etc.)
    repo_path = os.path.realpath(repo_path)

    # Check directory exists
    if not os.path.isdir(repo_path):
        errors.append(f"Directory does not exist: {repo_path}")
        return {"ok": False, "errors": errors, "warnings": warnings}

    # Check readable
    if not os.access(repo_path, os.R_OK):
        errors.append(f"Directory is not readable: {repo_path}")
        return {"ok": False, "errors": errors, "warnings": warnings}

    # Check git repository
    git_dir = os.path.join(repo_path, ".git")
    if not os.path.isdir(git_dir):
        errors.append(f"Not a git repository (no .git directory): {repo_path}")
        return {"ok": False, "errors": errors, "warnings": warnings}

    # Check git CLI available
    try:
        subprocess.run(
            ["git", "--version"],
            capture_output=True, timeout=5, check=True,
        )
    except (FileNotFoundError, subprocess.SubprocessError):
        errors.append("git CLI is not available in PATH")
        return {"ok": False, "errors": errors, "warnings": warnings}

    return {"ok": True, "errors": errors, "warnings": warnings, "canonical_path": repo_path}
