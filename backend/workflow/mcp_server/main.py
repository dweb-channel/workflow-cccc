"""
Workflow MCP Server - JSON-RPC protocol layer

Runs in stdio mode for agent runtimes (e.g., Claude Code).

Protocol: JSON-RPC 2.0 over stdin/stdout
"""

from __future__ import annotations

import json
import sys
from typing import Any, Dict, Optional

from .server import MCP_TOOLS, MCPError, handle_tool_call

__version__ = "0.1.0"


def _read_message() -> Optional[Dict[str, Any]]:
    """Read a single JSON-RPC message from stdin."""
    try:
        line = sys.stdin.readline()
        if not line:
            return None
        return json.loads(line.strip())
    except Exception:
        return None


def _write_message(msg: Dict[str, Any]) -> None:
    """Write a single JSON-RPC message to stdout."""
    sys.stdout.write(json.dumps(msg, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def _make_response(id: Any, result: Any) -> Dict[str, Any]:
    """Build a JSON-RPC success response."""
    return {"jsonrpc": "2.0", "id": id, "result": result}


def _make_error(id: Any, code: int, message: str, data: Any = None) -> Dict[str, Any]:
    """Build a JSON-RPC error response."""
    error: Dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        error["data"] = data
    return {"jsonrpc": "2.0", "id": id, "error": error}


def handle_request(req: Dict[str, Any]) -> Dict[str, Any]:
    """Handle an MCP JSON-RPC request."""
    req_id = req.get("id")
    method = str(req.get("method") or "")
    params = req.get("params") or {}

    # MCP protocol methods
    if method == "initialize":
        return _make_response(req_id, {
            "protocolVersion": "2024-11-05",
            "capabilities": {
                "tools": {},
                "resources": {},
                "prompts": {},
            },
            "serverInfo": {
                "name": "workflow-mcp",
                "version": __version__,
            },
        })

    if method.startswith("notifications/"):
        # Notifications do not require a response
        return {}

    if method == "tools/list":
        return _make_response(req_id, {"tools": MCP_TOOLS})

    # Optional MCP surfaces (return empty)
    if method == "resources/list":
        return _make_response(req_id, {"resources": []})

    if method == "prompts/list":
        return _make_response(req_id, {"prompts": []})

    # Common no-op requests
    if method == "ping":
        return _make_response(req_id, {})

    if method == "logging/setLevel":
        return _make_response(req_id, {})

    if method == "tools/call":
        tool_name = str(params.get("name") or "")
        arguments = params.get("arguments") or {}
        if not isinstance(arguments, dict):
            arguments = {}

        try:
            result = handle_tool_call(tool_name, arguments)
            return _make_response(req_id, {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(result, ensure_ascii=False, indent=2),
                    }
                ],
            })
        except MCPError as e:
            return _make_response(req_id, {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps({
                            "error": {
                                "code": e.code,
                                "message": e.message,
                                "details": e.details,
                            }
                        }, ensure_ascii=False, indent=2),
                    }
                ],
                "isError": True,
            })
        except Exception as e:
            return _make_response(req_id, {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps({
                            "error": {
                                "code": "internal_error",
                                "message": str(e),
                            }
                        }, ensure_ascii=False, indent=2),
                    }
                ],
                "isError": True,
            })

    # Unknown method
    return _make_error(req_id, -32601, f"Method not found: {method}")


def main() -> int:
    """MCP server main loop (stdio mode)."""
    while True:
        msg = _read_message()
        if msg is None:
            break

        resp = handle_request(msg)
        if resp:  # Notifications return {}
            _write_message(resp)

    return 0
