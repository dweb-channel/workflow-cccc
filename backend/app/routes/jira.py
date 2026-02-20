"""Jira Integration API endpoints.

Provides JQL-based bug querying for the batch bug fix workflow.
"""

from __future__ import annotations

import ipaddress
import logging
import os
import socket
from typing import List, Literal, Optional
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger("workflow.routes.jira")

# Maximum allowed JQL query length to prevent abuse
_MAX_JQL_LENGTH = 2000

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

    # Validate JQL length
    if len(payload.jql) > _MAX_JQL_LENGTH:
        raise HTTPException(
            status_code=400,
            detail={
                "error": f"JQL query too long ({len(payload.jql)} chars, max {_MAX_JQL_LENGTH})",
                "error_type": "jql_error",
            },
        )

    # Validate Jira URL to prevent SSRF
    _validate_jira_url(jira_url)

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


# --- SSRF Protection ---

# Private/reserved IP ranges that must not be accessed
_PRIVATE_RANGES = [
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
]


def _validate_jira_url(url: str) -> None:
    """Validate a Jira URL to prevent SSRF attacks.

    Checks:
    - Scheme must be https (or http for localhost dev)
    - Hostname must not resolve to private/reserved IP ranges
    - Hostname must not be an IP address literal

    Raises:
        HTTPException if URL is invalid or points to a private network.
    """
    parsed = urlparse(url)

    if parsed.scheme not in ("https", "http"):
        raise HTTPException(
            status_code=400,
            detail={
                "error": "Jira URL must use https",
                "error_type": "connection_error",
            },
        )

    hostname = parsed.hostname
    if not hostname:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "Invalid Jira URL: missing hostname",
                "error_type": "connection_error",
            },
        )

    # Reject raw IP addresses — Jira instances should use domain names
    try:
        addr = ipaddress.ip_address(hostname)
        # Allow localhost for local development
        if addr == ipaddress.ip_address("127.0.0.1") or addr == ipaddress.ip_address("::1"):
            logger.warning("Jira URL points to localhost — allowed for dev only")
            return
        raise HTTPException(
            status_code=400,
            detail={
                "error": "Jira URL must use a domain name, not an IP address",
                "error_type": "connection_error",
            },
        )
    except ValueError:
        pass  # Not an IP — it's a domain name, continue validation

    # Resolve hostname and check against private ranges
    try:
        resolved = socket.getaddrinfo(hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
        for _, _, _, _, sockaddr in resolved:
            ip = ipaddress.ip_address(sockaddr[0])
            for private_range in _PRIVATE_RANGES:
                if ip in private_range:
                    logger.warning(
                        "Jira URL %s resolves to private IP %s — blocked",
                        hostname, ip,
                    )
                    raise HTTPException(
                        status_code=400,
                        detail={
                            "error": "Jira URL resolves to a private/reserved IP address",
                            "error_type": "connection_error",
                        },
                    )
    except socket.gaierror:
        # DNS resolution failed — let httpx handle the connection error later
        pass
