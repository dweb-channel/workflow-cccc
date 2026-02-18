"""Workflow runtime settings — tunable parameters for pipeline execution.

All values read from environment variables with sensible defaults matching
the original hardcoded values. Import from here instead of hardcoding.

Infrastructure config (Temporal address, API host, CLI path, tokens) stays
in workflow/config.py.
"""

from __future__ import annotations

import os


def _int(key: str, default: int) -> int:
    return int(os.getenv(key, str(default)))


def _float(key: str, default: float) -> float:
    return float(os.getenv(key, str(default)))


def _str(key: str, default: str) -> str:
    return os.getenv(key, default)


# =====================================================================
# Spec Pipeline (design-to-spec)
# =====================================================================

# Max parallel Claude CLI subprocesses for component analysis
SPEC_CLI_CONCURRENCY = _int("SPEC_CLI_CONCURRENCY", 3)

# Stagger delay per component (seconds) to avoid rate limits
SPEC_COMPONENT_STAGGER_DELAY = _float("SPEC_COMPONENT_STAGGER_DELAY", 2.0)

# SpecAnalyzer LLM parameters
SPEC_ANALYZER_MAX_TOKENS = _int("SPEC_ANALYZER_MAX_TOKENS", 4096)
SPEC_ANALYZER_MAX_RETRIES = _int("SPEC_ANALYZER_MAX_RETRIES", 2)

# Claude CLI call timeouts (seconds)
SPEC_PASS1_TIMEOUT = _float("SPEC_PASS1_TIMEOUT", 300.0)
SPEC_PASS2_TIMEOUT = _float("SPEC_PASS2_TIMEOUT", 120.0)
SPEC_JSON_CORRECTION_TIMEOUT = _float("SPEC_JSON_CORRECTION_TIMEOUT", 120.0)

# Temporal workflow timeouts
SPEC_HEARTBEAT_INTERVAL = _float("SPEC_HEARTBEAT_INTERVAL", 60.0)
SPEC_WORKFLOW_MIN_TIMEOUT_MINUTES = _int("SPEC_WORKFLOW_MIN_TIMEOUT_MINUTES", 15)
SPEC_WORKFLOW_PER_COMPONENT_MINUTES = _int("SPEC_WORKFLOW_PER_COMPONENT_MINUTES", 10)
SPEC_WORKFLOW_OVERHEAD_MINUTES = _int("SPEC_WORKFLOW_OVERHEAD_MINUTES", 5)
SPEC_WORKFLOW_HEARTBEAT_TIMEOUT_MINUTES = _int("SPEC_WORKFLOW_HEARTBEAT_TIMEOUT_MINUTES", 10)


# =====================================================================
# Batch Pipeline (bug fix)
# =====================================================================

# Git subprocess timeout (seconds)
GIT_COMMAND_TIMEOUT = _int("GIT_COMMAND_TIMEOUT", 60)

# Temporal workflow timeouts
BATCH_HEARTBEAT_INTERVAL = _float("BATCH_HEARTBEAT_INTERVAL", 60.0)
BATCH_WORKFLOW_MIN_TIMEOUT_MINUTES = _int("BATCH_WORKFLOW_MIN_TIMEOUT_MINUTES", 30)
BATCH_WORKFLOW_PER_BUG_MINUTES = _int("BATCH_WORKFLOW_PER_BUG_MINUTES", 15)
BATCH_WORKFLOW_HEARTBEAT_TIMEOUT_MINUTES = _int("BATCH_WORKFLOW_HEARTBEAT_TIMEOUT_MINUTES", 15)

# DB sync retry attempts (with exponential backoff)
BATCH_DB_SYNC_MAX_ATTEMPTS = _int("BATCH_DB_SYNC_MAX_ATTEMPTS", 4)


# =====================================================================
# LLM / Claude CLI
# =====================================================================

# Default retry base delay for exponential backoff (seconds)
LLM_RETRY_BASE_DELAY = _float("LLM_RETRY_BASE_DELAY", 10.0)

# Min delay when rate-limited (overrides base delay)
LLM_RATE_LIMIT_MIN_DELAY = _float("LLM_RATE_LIMIT_MIN_DELAY", 30.0)

# Default/max timeout for LLM agent nodes (seconds)
LLM_AGENT_DEFAULT_TIMEOUT = _float("LLM_AGENT_DEFAULT_TIMEOUT", 300.0)
LLM_AGENT_MAX_TIMEOUT = _float("LLM_AGENT_MAX_TIMEOUT", 3600.0)


# =====================================================================
# HTTP Clients (Worker → FastAPI SSE push, Figma API)
# =====================================================================

SSE_HTTP_TIMEOUT = _float("SSE_HTTP_TIMEOUT", 5.0)
SSE_HTTP_MAX_CONNECTIONS = _int("SSE_HTTP_MAX_CONNECTIONS", 10)
SSE_HTTP_MAX_KEEPALIVE = _int("SSE_HTTP_MAX_KEEPALIVE", 5)

FIGMA_HTTP_TIMEOUT = _float("FIGMA_HTTP_TIMEOUT", 60.0)


# =====================================================================
# Pipeline Policies
# =====================================================================

# failure_policy: "skip" (default) | "stop" | "retry"
#   skip — continue to next bug on failure (default, existing behavior)
#   stop — abort pipeline on first bug failure
#   retry — retry failed bugs up to max_retries (graph loop handles this)
FAILURE_POLICY = _str("FAILURE_POLICY", "skip")

# validation_level: "minimal" | "standard" (default) | "thorough"
#   minimal — quick syntax/import check only
#   standard — default verification (current behavior)
#   thorough — full test suite + integration checks
VALIDATION_LEVEL = _str("VALIDATION_LEVEL", "standard")
