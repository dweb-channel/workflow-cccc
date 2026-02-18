"""Jira Integration API endpoints.

Provides JQL-based bug querying for the batch bug fix workflow.
"""

from __future__ import annotations

import logging
import os
from typing import List, Literal, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger("workflow.routes.jira")

router = APIRouter(prefix="/api/v2/jira", tags=["jira"])


# --- Schemas ---


class JiraQueryRequest(BaseModel):
    """Request for POST /api/v2/jira/query."""
    jql: str = Field(..., description="JQL query string")
    jira_url: Optional[str] = Field(
        None,
        description="Jira instance URL (e.g., https://company.atlassian.net). "
        "Falls back to JIRA_URL env var if not provided.",
    )
    email: Optional[str] = Field(
        None,
        description="Jira user email. Falls back to JIRA_EMAIL env var if not provided.",
    )
    api_token: Optional[str] = Field(
        None,
        description="Jira API token. Falls back to JIRA_API_TOKEN env var if not provided.",
    )
    max_results: int = Field(
        default=50,
        ge=1,
        le=100,
        description="Maximum number of results to return (default 50, max 100)",
    )


class JiraBugInfo(BaseModel):
    """Bug information from Jira."""
    key: str
    summary: str
    status: str
    url: str
    priority: Optional[str] = None
    assignee: Optional[str] = None


class JiraQueryResponse(BaseModel):
    """Response for POST /api/v2/jira/query."""
    bugs: List[JiraBugInfo]
    total: int
    jql: str


class JiraErrorResponse(BaseModel):
    """Error response for Jira API failures."""
    error: str
    error_type: Literal["auth_failed", "jql_error", "connection_error", "unknown"]
    details: Optional[str] = None


# --- Endpoints ---


@router.post(
    "/query",
    response_model=JiraQueryResponse,
    responses={
        400: {"model": JiraErrorResponse, "description": "JQL syntax error"},
        401: {"model": JiraErrorResponse, "description": "Authentication failed"},
        502: {"model": JiraErrorResponse, "description": "Jira connection error"},
    },
)
async def query_jira_bugs(payload: JiraQueryRequest):
    """Query Jira for bugs using JQL.

    Credentials can be provided in the request body or via environment variables:
    - JIRA_URL: Jira instance URL
    - JIRA_EMAIL: User email
    - JIRA_API_TOKEN: API token

    Example JQL queries:
    - `project = MYPROJECT AND type = Bug`
    - `project = MYPROJECT AND type = Bug AND status = Open`
    - `assignee = currentUser() AND type = Bug`
    """
    import httpx
    import base64

    # Resolve credentials (request body > env vars)
    jira_url = payload.jira_url or os.environ.get("JIRA_URL")
    email = payload.email or os.environ.get("JIRA_EMAIL")
    api_token = payload.api_token or os.environ.get("JIRA_API_TOKEN")

    # Validate required credentials
    missing = []
    if not jira_url:
        missing.append("jira_url (or JIRA_URL env var)")
    if not email:
        missing.append("email (or JIRA_EMAIL env var)")
    if not api_token:
        missing.append("api_token (or JIRA_API_TOKEN env var)")

    if missing:
        raise HTTPException(
            status_code=400,
            detail={
                "error": f"Missing required credentials: {', '.join(missing)}",
                "error_type": "auth_failed",
            },
        )

    # Normalize Jira URL (remove trailing slash)
    jira_url = jira_url.rstrip("/")

    # Build auth header (Basic auth with email:token)
    auth_string = f"{email}:{api_token}"
    auth_bytes = base64.b64encode(auth_string.encode()).decode()

    # Build request to Jira REST API
    search_url = f"{jira_url}/rest/api/3/search"
    headers = {
        "Authorization": f"Basic {auth_bytes}",
        "Accept": "application/json",
    }
    params = {
        "jql": payload.jql,
        "maxResults": payload.max_results,
        "fields": "summary,status,priority,assignee",
    }

    logger.info(f"Jira query: JQL='{payload.jql}', maxResults={payload.max_results}")

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(search_url, headers=headers, params=params)

            if response.status_code == 401:
                raise HTTPException(
                    status_code=401,
                    detail={
                        "error": "Authentication failed. Check email and API token.",
                        "error_type": "auth_failed",
                    },
                )

            if response.status_code == 400:
                error_data = response.json()
                error_messages = error_data.get("errorMessages", [])
                raise HTTPException(
                    status_code=400,
                    detail={
                        "error": "Invalid JQL query",
                        "error_type": "jql_error",
                        "details": "; ".join(error_messages) if error_messages else str(error_data),
                    },
                )

            if response.status_code != 200:
                raise HTTPException(
                    status_code=502,
                    detail={
                        "error": f"Jira API returned status {response.status_code}",
                        "error_type": "unknown",
                        "details": response.text[:500],
                    },
                )

            data = response.json()

    except httpx.ConnectError as e:
        logger.error(f"Jira connection error: {e}")
        raise HTTPException(
            status_code=502,
            detail={
                "error": f"Failed to connect to Jira: {jira_url}",
                "error_type": "connection_error",
                "details": str(e),
            },
        )
    except httpx.TimeoutException:
        raise HTTPException(
            status_code=502,
            detail={
                "error": "Jira request timed out",
                "error_type": "connection_error",
            },
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Jira query error: {e}")
        raise HTTPException(
            status_code=500,
            detail={
                "error": "Unexpected error querying Jira",
                "error_type": "unknown",
                "details": str(e),
            },
        )

    # Parse response
    issues = data.get("issues", [])
    total = data.get("total", len(issues))

    bugs: List[JiraBugInfo] = []
    for issue in issues:
        key = issue.get("key", "")
        fields = issue.get("fields", {})

        status_obj = fields.get("status", {})
        status = status_obj.get("name", "Unknown") if status_obj else "Unknown"

        priority_obj = fields.get("priority")
        priority = priority_obj.get("name") if priority_obj else None

        assignee_obj = fields.get("assignee")
        assignee = assignee_obj.get("displayName") if assignee_obj else None

        issue_url = f"{jira_url}/browse/{key}"

        bugs.append(JiraBugInfo(
            key=key,
            summary=fields.get("summary", ""),
            status=status,
            url=issue_url,
            priority=priority,
            assignee=assignee,
        ))

    logger.info(f"Jira query returned {len(bugs)} bugs (total: {total})")

    return JiraQueryResponse(
        bugs=bugs,
        total=total,
        jql=payload.jql,
    )
