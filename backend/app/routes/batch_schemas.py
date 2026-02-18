"""Pydantic schemas for Batch Bug Fix API endpoints."""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, field_validator
from urllib.parse import urlparse


class BatchBugFixConfig(BaseModel):
    """Configuration for batch bug fix job."""
    validation_level: Literal["minimal", "standard", "thorough"] = "standard"
    failure_policy: Literal["stop", "skip", "retry"] = "skip"
    max_retries: int = Field(default=3, ge=1, le=10)


class BatchBugFixRequest(BaseModel):
    """Request for POST /api/v2/batch/bug-fix."""
    jira_urls: List[str] = Field(..., min_length=1, description="List of Jira bug URLs")
    cwd: Optional[str] = Field(
        None,
        description="Working directory for Claude CLI (defaults to current directory)",
    )
    workspace_id: Optional[str] = Field(
        None,
        description="Workspace ID to associate this job with (inherits config_defaults)",
    )
    config: Optional[BatchBugFixConfig] = None
    dry_run: bool = Field(
        default=False,
        description="If true, return a preview without starting Temporal workflow",
    )

    @field_validator("jira_urls")
    @classmethod
    def validate_jira_urls(cls, urls: List[str]) -> List[str]:
        """Validate that each URL is a reachable Jira-like URL.

        Rejects:
        - Non-HTTP(S) URLs
        - Reserved/example domains (example.com, localhost, etc.)
        - Malformed URLs without proper host
        """
        _BLOCKED_HOSTS = {"example.com", "example.org", "example.net", "localhost", "127.0.0.1"}

        invalid = []
        for url in urls:
            url = url.strip()
            if not url:
                invalid.append(("(empty)", "URL cannot be empty"))
                continue
            parsed = urlparse(url)
            if parsed.scheme not in ("http", "https"):
                invalid.append((url, f"must use http or https (got '{parsed.scheme}')"))
                continue
            host = (parsed.hostname or "").lower()
            if not host:
                invalid.append((url, "missing hostname"))
                continue
            # Check blocked domains (exact match or subdomain)
            base_host = ".".join(host.rsplit(".", 2)[-2:]) if "." in host else host
            if base_host in _BLOCKED_HOSTS or host in _BLOCKED_HOSTS:
                invalid.append((url, f"'{host}' is a reserved/example domain, not a real Jira instance"))
                continue

        if invalid:
            details = "; ".join(f"{u}: {reason}" for u, reason in invalid)
            raise ValueError(f"Invalid Jira URL(s): {details}")
        return urls


class BugStepInfo(BaseModel):
    """Execution step information for a bug."""
    step: str
    label: str
    status: Literal["pending", "in_progress", "completed", "failed"] = "pending"
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    duration_ms: Optional[float] = None
    output_preview: Optional[str] = None
    error: Optional[str] = None
    attempt: Optional[int] = None


class BugStatus(BaseModel):
    """Status of a single bug in the batch."""
    url: str
    status: Literal["pending", "in_progress", "completed", "failed", "skipped"]
    error: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    steps: Optional[List[BugStepInfo]] = None
    retry_count: Optional[int] = None


class BatchBugFixResponse(BaseModel):
    """Response for POST /api/v2/batch/bug-fix."""
    job_id: str
    status: Literal["started", "running", "completed", "failed", "cancelled"]
    total_bugs: int
    created_at: str


class DryRunBugPreview(BaseModel):
    """Preview of a single bug in dry-run mode."""
    url: str
    jira_key: str
    expected_steps: List[str] = Field(
        description="Ordered list of visible pipeline steps",
    )


class DryRunResponse(BaseModel):
    """Response for POST /api/v2/batch/bug-fix with dry_run=true."""
    dry_run: Literal[True] = True
    total_bugs: int
    cwd: str
    config: BatchBugFixConfig
    bugs: List[DryRunBugPreview]
    expected_steps_per_bug: List[str] = Field(
        description="Canonical step labels for each bug",
    )


class BatchJobStatusResponse(BaseModel):
    """Response for GET /api/v2/batch/bug-fix/{job_id}."""
    job_id: str
    status: Literal["started", "running", "completed", "failed", "cancelled"]
    total_bugs: int
    completed: int
    failed: int
    skipped: int
    in_progress: int
    pending: int
    bugs: List[BugStatus]
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class BatchJobSummary(BaseModel):
    """Summary of a batch job for list view."""
    job_id: str
    status: Literal["started", "running", "completed", "failed", "cancelled"]
    total_bugs: int
    completed: int
    failed: int
    created_at: str
    updated_at: str


class BatchJobListResponse(BaseModel):
    """Response for GET /api/v2/batch/bug-fix (list)."""
    jobs: List[BatchJobSummary]
    total: int
    page: int
    page_size: int


class JobControlResponse(BaseModel):
    """Response for job control operations (cancel/pause/resume)."""
    success: bool
    job_id: str
    status: str
    message: str


class BatchDeleteRequest(BaseModel):
    """Request for batch deletion."""
    job_ids: List[str] = Field(..., description="List of job IDs to delete")


class BatchDeleteResponse(BaseModel):
    """Response for batch deletion."""
    deleted: List[str]
    failed: List[str]
    message: str
