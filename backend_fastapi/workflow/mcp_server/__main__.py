"""
Workflow MCP Server entrypoint.

Usage:
    python -m backend_fastapi.workflow.mcp_server
"""

from .main import main

if __name__ == "__main__":
    raise SystemExit(main())
