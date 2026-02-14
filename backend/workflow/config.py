"""Workflow configuration constants — single source of truth for all env vars."""

import os
import shutil

# Temporal
TEMPORAL_ADDRESS = os.getenv("TEMPORAL_ADDRESS", "localhost:7233")
TASK_QUEUE = os.getenv("TEMPORAL_TASK_QUEUE", "business-workflow-task-queue")

# Server binding — used by entrypoint / uvicorn
API_HOST = os.getenv("API_HOST", "0.0.0.0")
API_PORT = int(os.getenv("API_PORT", "8000"))

# Claude CLI — resolved once at import time
CLAUDE_CLI_PATH = os.getenv("CLAUDE_CLI_PATH") or shutil.which("claude") or "claude"

# Claude CLI permission mode — skip interactive permission prompts for batch execution
CLAUDE_SKIP_PERMISSIONS = os.getenv("CLAUDE_SKIP_PERMISSIONS", "true").lower() in ("true", "1", "yes")

# Claude CLI MCP config — path to MCP server config JSON file (e.g., for Jira access)
CLAUDE_MCP_CONFIG = os.getenv("CLAUDE_MCP_CONFIG", "")

# Figma REST API — Personal Access Token for design file access
FIGMA_TOKEN = os.getenv("FIGMA_TOKEN", "")
