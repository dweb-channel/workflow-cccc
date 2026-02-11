"""Filesystem Browse API endpoint.

Provides a server-side directory listing for the frontend directory picker.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

router = APIRouter(prefix="/api/v2/filesystem", tags=["filesystem"])


class DirectoryEntry(BaseModel):
    """A single directory entry."""
    name: str
    path: str
    is_dir: bool


class BrowseResponse(BaseModel):
    """Response for directory browse endpoint."""
    current_path: str
    parent_path: Optional[str]
    entries: List[DirectoryEntry]


@router.get("/browse", response_model=BrowseResponse)
async def browse_directory(
    path: str = Query(default="/", description="Directory path to browse"),
):
    """List directories and files at the given path.

    Returns subdirectories (sorted) for the directory picker UI.
    Only lists directories, not regular files, to keep the picker focused.
    """
    target = Path(path).resolve()

    if not target.exists():
        raise HTTPException(status_code=404, detail=f"Path not found: {path}")
    if not target.is_dir():
        raise HTTPException(status_code=400, detail=f"Not a directory: {path}")

    entries: List[DirectoryEntry] = []

    try:
        for item in sorted(target.iterdir(), key=lambda p: p.name.lower()):
            # Skip hidden files/directories
            if item.name.startswith("."):
                continue
            # Only include directories
            if item.is_dir():
                entries.append(DirectoryEntry(
                    name=item.name,
                    path=str(item),
                    is_dir=True,
                ))
    except PermissionError:
        raise HTTPException(status_code=403, detail=f"Permission denied: {path}")

    parent_path = str(target.parent) if target != target.parent else None

    return BrowseResponse(
        current_path=str(target),
        parent_path=parent_path,
        entries=entries,
    )
