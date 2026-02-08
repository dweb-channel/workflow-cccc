"""CCCC Client for Workflow Integration.

This module provides a Python interface to communicate with the local CCCC daemon,
allowing Temporal workflow activities to send messages to and receive responses from
CCCC peers (agents).

Usage:
    from .cccc_client import CCCCClient

    client = CCCCClient(group_id="g_xxx")

    # Send a message to a peer
    result = await client.send_to_peer(
        peer_id="superpowers-peer",
        text="/brainstorm Analyze this requirement...",
    )

    # Wait for peer response
    response = await client.wait_for_response(
        from_peer="superpowers-peer",
        timeout=120.0
    )
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import socket
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("workflow.cccc_client")


@dataclass
class DaemonPaths:
    """Paths for CCCC daemon communication."""
    home: Path

    @property
    def daemon_dir(self) -> Path:
        return self.home / "daemon"

    @property
    def sock_path(self) -> Path:
        return self.daemon_dir / "ccccd.sock"

    @property
    def addr_path(self) -> Path:
        return self.daemon_dir / "ccccd.addr.json"


def _ensure_home() -> Path:
    """Get the CCCC home directory."""
    env_home = os.environ.get("CCCC_HOME")
    if env_home:
        return Path(env_home)
    return Path.home() / ".cccc"


def _default_paths() -> DaemonPaths:
    return DaemonPaths(home=_ensure_home())


def _read_json(path: Path) -> Optional[Dict[str, Any]]:
    """Read a JSON file, return None on error."""
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return None


def _get_daemon_endpoint(paths: Optional[DaemonPaths] = None) -> Dict[str, Any]:
    """Get the daemon endpoint configuration."""
    p = paths or _default_paths()
    doc = _read_json(p.addr_path)
    if isinstance(doc, dict):
        transport = str(doc.get("transport") or "").strip().lower()
        if transport == "tcp":
            host = str(doc.get("host") or "").strip() or "127.0.0.1"
            try:
                port = int(doc.get("port") or 0)
            except Exception:
                port = 0
            if port > 0:
                return {"transport": "tcp", "host": host, "port": port}
        if transport == "unix":
            path = str(doc.get("path") or "").strip()
            if path:
                return {"transport": "unix", "path": path}
    # Fallback to Unix socket
    return {"transport": "unix", "path": str(p.sock_path)}


def call_daemon(
    req: Dict[str, Any],
    *,
    paths: Optional[DaemonPaths] = None,
    timeout_s: float = 60.0
) -> Dict[str, Any]:
    """Call the CCCC daemon via IPC.

    Args:
        req: Request dictionary with 'op' and 'args' keys
        paths: Optional custom daemon paths
        timeout_s: Socket timeout in seconds

    Returns:
        Response dictionary with 'ok', 'result', and optional 'error' keys
    """
    p = paths or _default_paths()

    # Validate request structure
    if "op" not in req:
        return {
            "ok": False,
            "error": {"code": "invalid_request", "message": "missing 'op' field"},
        }

    request_data = {"v": 1, "op": req["op"], "args": req.get("args", {})}

    try:
        ep = _get_daemon_endpoint(p)
        transport = str(ep.get("transport") or "").strip().lower()

        if transport == "tcp":
            host = str(ep.get("host") or "127.0.0.1").strip() or "127.0.0.1"
            port = int(ep.get("port") or 0)
            if port <= 0:
                raise RuntimeError("invalid tcp daemon endpoint")

            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            try:
                s.settimeout(timeout_s)
                s.connect((host, port))
                s.sendall((json.dumps(request_data, ensure_ascii=False) + "\n").encode("utf-8"))
                with s.makefile("rb") as f:
                    line = f.readline(4_000_000)
            finally:
                try:
                    s.close()
                except Exception:
                    pass
        else:
            # Unix socket
            af_unix = getattr(socket, "AF_UNIX", None)
            if af_unix is None:
                raise RuntimeError("AF_UNIX not supported on this platform")

            sock_path = str(ep.get("path") or p.sock_path)
            s = socket.socket(af_unix, socket.SOCK_STREAM)
            try:
                s.settimeout(timeout_s)
                s.connect(sock_path)
                s.sendall((json.dumps(request_data, ensure_ascii=False) + "\n").encode("utf-8"))
                with s.makefile("rb") as f:
                    line = f.readline(4_000_000)
            finally:
                try:
                    s.close()
                except Exception:
                    pass

        if not line:
            return {
                "ok": False,
                "error": {"code": "empty_response", "message": "daemon returned empty response"},
            }

        return json.loads(line.decode("utf-8"))

    except socket.timeout:
        return {
            "ok": False,
            "error": {"code": "timeout", "message": f"daemon request timed out after {timeout_s}s"},
        }
    except ConnectionRefusedError:
        return {
            "ok": False,
            "error": {"code": "connection_refused", "message": "daemon not running"},
        }
    except Exception as e:
        return {
            "ok": False,
            "error": {"code": "daemon_error", "message": str(e)},
        }


class CCCCClient:
    """Client for communicating with CCCC daemon from workflow activities.

    This client allows Temporal workflow activities to send messages to CCCC peers
    and wait for their responses.

    Architecture: Workflow → Foreman → Peers → Foreman → Workflow
    - Sends requests to foreman (master) who coordinates peer execution
    - Foreman delegates to appropriate peers and consolidates results
    - Uses a single workflow actor for both sending and receiving

    Args:
        group_id: The CCCC working group ID
        actor_id: The actor ID for workflow communication (default: "workflow-activity")
        foreman_id: The foreman actor ID to coordinate with (default: "master")
        mock: If True, return mock responses instead of calling the daemon
    """

    def __init__(
        self,
        group_id: str,
        actor_id: str = "workflow-activity",
        foreman_id: str = "master",
        mock: bool = False,
    ):
        self.group_id = group_id
        self.actor_id = actor_id
        self.foreman_id = foreman_id
        # Keep backward compatibility
        self.send_as = actor_id
        self.inbox_as = actor_id
        self.mock = mock
        self._paths = _default_paths()

    def _call_daemon(self, req: Dict[str, Any]) -> Dict[str, Any]:
        """Call daemon and handle errors."""
        if self.mock:
            return {"ok": True, "result": {"mock": True}}

        resp = call_daemon(req, paths=self._paths)
        if not resp.get("ok"):
            err = resp.get("error", {})
            logger.error(f"Daemon error: {err}")
        return resp

    def send_message(
        self,
        text: str,
        to: List[str],
        priority: str = "normal",
    ) -> Dict[str, Any]:
        """Send a message to specified recipients.

        Args:
            text: Message text
            to: List of recipient actor IDs or selectors (@all, @peers, etc.)
            priority: Message priority (normal or attention)

        Returns:
            Response from daemon
        """
        if self.mock:
            logger.info(f"[MOCK] Sending to {to}: {text[:100]}...")
            return {"ok": True, "result": {"event": {"id": "mock-event-id"}}}

        return self._call_daemon({
            "op": "send",
            "args": {
                "group_id": self.group_id,
                "text": text,
                "by": self.send_as,
                "to": to,
                "path": "",
                "priority": priority,
            },
        })

    def send_to_peer(
        self,
        peer_id: str,
        text: str,
        priority: str = "normal",
    ) -> Dict[str, Any]:
        """Send a message to a specific peer.

        Args:
            peer_id: The peer's actor ID
            text: Message text (can include commands like /brainstorm)
            priority: Message priority

        Returns:
            Response from daemon with event info including timestamp
        """
        resp = self.send_message(text=text, to=[peer_id], priority=priority)
        # Extract and log send timestamp for debugging
        if resp.get("ok"):
            event = resp.get("result", {}).get("event", {})
            ts = event.get("ts", "")
            logger.info(f"Message sent at {ts}, event_id={event.get('id', '')}")
        return resp

    def get_inbox(
        self,
        limit: int = 50,
        kind_filter: str = "chat",
    ) -> Dict[str, Any]:
        """Get unread messages from inbox.

        Args:
            limit: Maximum number of messages to return
            kind_filter: Filter type (all, chat, notify)

        Returns:
            Response with messages list
        """
        if self.mock:
            return {"ok": True, "result": {"messages": [], "cursor": {}}}

        return self._call_daemon({
            "op": "inbox_list",
            "args": {
                "group_id": self.group_id,
                "actor_id": self.inbox_as,
                "by": self.inbox_as,
                "limit": limit,
                "kind_filter": kind_filter,
            },
        })

    def mark_read(self, event_id: str) -> Dict[str, Any]:
        """Mark messages as read up to the specified event.

        Args:
            event_id: Event ID to mark as read up to

        Returns:
            Response from daemon
        """
        if self.mock:
            return {"ok": True, "result": {}}

        return self._call_daemon({
            "op": "inbox_mark_read",
            "args": {
                "group_id": self.group_id,
                "actor_id": self.inbox_as,
                "event_id": event_id,
                "by": self.inbox_as,
            },
        })

    def get_ledger_tail(
        self,
        limit: int = 50,
        max_chars: int = 16000,
    ) -> Dict[str, Any]:
        """Get recent chat messages from ledger (not dependent on read status).

        Args:
            limit: Maximum number of messages to return
            max_chars: Maximum total characters across returned messages

        Returns:
            Response with ledger_tail list
        """
        if self.mock:
            return {"ok": True, "result": {"ledger_tail": []}}

        # Use bootstrap to get ledger_tail
        return self._call_daemon({
            "op": "bootstrap",
            "args": {
                "group_id": self.group_id,
                "actor_id": self.send_as,
                "ledger_tail_limit": limit,
                "ledger_tail_max_chars": max_chars,
                "inbox_limit": 0,  # Don't need inbox
            },
        })

    def list_actors(self) -> Dict[str, Any]:
        """List all actors in the current group.

        Returns:
            Response with actors list containing id, role, title, enabled, running
        """
        if self.mock:
            return {"ok": True, "result": {"actors": []}}

        return self._call_daemon({
            "op": "actor_list",
            "args": {
                "group_id": self.group_id,
            },
        })

    async def wait_for_response(
        self,
        from_peer: str,
        after_ts: Optional[str] = None,
        timeout: Optional[float] = None,
        poll_interval: float = 2.0,
    ) -> Optional[str]:
        """Wait for a response from a specific peer using dedicated inbox.

        Uses workflow-inbox actor's inbox to receive responses. Since this is a
        dedicated inbox that only the workflow reads from, "unread" status is reliable.
        Human users don't read from workflow-inbox, so messages won't be marked read.

        Args:
            from_peer: The peer ID to wait for
            after_ts: Only consider messages with timestamp > this value (ISO format)
            timeout: Maximum time to wait in seconds (None = wait indefinitely)
            poll_interval: How often to check for new messages

        Returns:
            The peer's response text, or None if timeout
        """
        if self.mock:
            await asyncio.sleep(0.1)
            return f"[MOCK] Response from {from_peer}"

        start_time = time.time()
        timeout_str = f"{timeout}s" if timeout else "indefinitely"
        logger.info(f"Waiting for response from {from_peer}, after_ts={after_ts}, timeout={timeout_str}")

        while timeout is None or (time.time() - start_time) < timeout:
            resp = self.get_inbox(limit=50)

            if resp.get("ok"):
                # inbox_list returns unread messages
                messages = resp.get("result", {}).get("messages", [])
                logger.debug(f"Got {len(messages)} unread messages from {self.inbox_as} inbox")

                for msg in messages:
                    by = msg.get("by", "")
                    msg_ts = msg.get("ts", "")
                    # Text is inside 'data' field for inbox_list messages
                    data = msg.get("data", {})
                    text = data.get("text", "") if isinstance(data, dict) else ""
                    event_id = msg.get("id", "")

                    # Skip messages before our send timestamp
                    if after_ts and msg_ts and msg_ts <= after_ts:
                        continue

                    if by == from_peer:
                        logger.info(f"Found response from {from_peer} at {msg_ts}")
                        # Mark as read so we don't process it again
                        if event_id:
                            self.mark_read(event_id)
                        return text
            else:
                logger.warning(f"Failed to get inbox: {resp.get('error')}")

            await asyncio.sleep(poll_interval)

        logger.warning(f"Timeout waiting for response from {from_peer}")
        return None

    async def ask_peer(
        self,
        peer_id: str,
        prompt: str,
        command: Optional[str] = None,
        timeout: Optional[float] = None,
        via_foreman: bool = True,
    ) -> Optional[str]:
        """Send a prompt to a peer and wait for response.

        When via_foreman=True (default), sends to foreman who coordinates the peer.
        This integrates naturally with CCCC's collaboration model.

        Args:
            peer_id: The peer's actor ID
            prompt: The prompt text
            command: Optional command prefix (e.g., "/brainstorm")
            timeout: Maximum time to wait for response (None = wait indefinitely)
            via_foreman: If True, route through foreman; if False, send directly to peer

        Returns:
            The peer's response text, or None if timeout/error
        """
        # Build message
        base_text = f"{command} {prompt}" if command else prompt

        if via_foreman:
            # Send to foreman with peer context
            text = f"[Workflow 任务] 请让 {peer_id} 执行以下任务，完成后请回复结果：\n\n{base_text}"
            target = self.foreman_id
            wait_for = self.foreman_id
            logger.info(f"Sending task to foreman ({self.foreman_id}) for peer {peer_id}")
        else:
            # Direct peer communication (legacy mode)
            text = base_text
            target = peer_id
            wait_for = peer_id
            logger.info(f"Sending task directly to peer {peer_id}")

        # Send message
        send_resp = self.send_to_peer(peer_id=target, text=text)
        if not send_resp.get("ok"):
            logger.error(f"Failed to send to {target}: {send_resp.get('error')}")
            return None

        # Extract send timestamp to filter responses
        send_ts = send_resp.get("result", {}).get("event", {}).get("ts", "")

        # Wait for response from foreman or peer
        return await self.wait_for_response(
            from_peer=wait_for,
            after_ts=send_ts,
            timeout=timeout,
        )


# Convenience function for simple usage
async def ask_cccc_peer(
    peer_id: str,
    prompt: str,
    command: Optional[str] = None,
    group_id: Optional[str] = None,
    timeout: float = 120.0,
) -> Optional[str]:
    """Send a prompt to a CCCC peer and wait for response.

    Args:
        peer_id: The peer's actor ID
        prompt: The prompt text
        command: Optional command prefix (e.g., "/brainstorm")
        group_id: CCCC group ID (uses CCCC_GROUP_ID env var if not specified)
        timeout: Maximum time to wait for response

    Returns:
        The peer's response text, or None if timeout/error
    """
    gid = group_id or os.environ.get("CCCC_GROUP_ID", "")
    if not gid:
        logger.error("No group_id specified and CCCC_GROUP_ID not set")
        return None

    client = CCCCClient(group_id=gid)
    return await client.ask_peer(
        peer_id=peer_id,
        prompt=prompt,
        command=command,
        timeout=timeout,
    )


def list_all_groups(paths: Optional[DaemonPaths] = None) -> Dict[str, Any]:
    """List all CCCC working groups by reading from filesystem.

    This is a standalone function that doesn't require a group_id.
    Reads group.yaml files directly from ~/.cccc/groups/.

    Args:
        paths: Optional custom daemon paths

    Returns:
        Response with groups list containing group_id, title, state, running, etc.
    """
    try:
        import yaml

        p = paths or _default_paths()
        groups_dir = p.home / "groups"

        if not groups_dir.exists():
            return {"ok": True, "result": {"groups": []}}

        groups = []
        for group_path in groups_dir.iterdir():
            if not group_path.is_dir() or not group_path.name.startswith("g_"):
                continue

            group_yaml = group_path / "group.yaml"
            if not group_yaml.exists():
                continue

            try:
                with open(group_yaml, "r", encoding="utf-8") as f:
                    group_data = yaml.safe_load(f)
                    if group_data:
                        groups.append({
                            "group_id": group_data.get("group_id", group_path.name),
                            "title": group_data.get("title", ""),
                            "state": group_data.get("state", "unknown"),
                            "running": group_data.get("running", False),
                            "scopes": group_data.get("scopes", []),
                            "actors": group_data.get("actors", []),
                        })
            except Exception as e:
                logger.warning(f"Failed to read group {group_path.name}: {e}")
                continue

        return {"ok": True, "result": {"groups": groups}}

    except Exception as e:
        return {
            "ok": False,
            "error": {"code": "filesystem_error", "message": str(e)},
        }


def get_group_info(group_id: str, paths: Optional[DaemonPaths] = None) -> Dict[str, Any]:
    """Get detailed information about a specific group.

    Args:
        group_id: The group ID to get info for
        paths: Optional custom daemon paths

    Returns:
        Response with group info including scopes, state, etc.
    """
    return call_daemon(
        {"op": "group_info", "args": {"group_id": group_id}},
        paths=paths,
    )


def list_group_actors(group_id: str, paths: Optional[DaemonPaths] = None) -> Dict[str, Any]:
    """List all actors in a specific group.

    Args:
        group_id: The group ID to list actors for
        paths: Optional custom daemon paths

    Returns:
        Response with actors list
    """
    return call_daemon(
        {"op": "actor_list", "args": {"group_id": group_id}},
        paths=paths,
    )


def send_cross_group_message(
    source_group_id: str,
    target_group_id: str,
    text: str,
    sender_id: str = "workflow-api",
    to: Optional[List[str]] = None,
    priority: str = "normal",
    paths: Optional[DaemonPaths] = None,
) -> Dict[str, Any]:
    """Send a message to a different CCCC group.

    Uses the dst_group_id parameter for cross-group communication.

    Args:
        source_group_id: The source group ID (sender's group)
        target_group_id: The target group ID to send message to
        text: Message text
        sender_id: Sender actor ID (default: workflow-api)
        to: Recipients in target group (default: @all)
        priority: Message priority (normal or attention)
        paths: Optional custom daemon paths

    Returns:
        Response from daemon with event info
    """
    return call_daemon(
        {
            "op": "send",
            "args": {
                "group_id": source_group_id,
                "dst_group_id": target_group_id,
                "text": text,
                "by": sender_id,
                "to": to or ["@all"],
                "path": "",
                "priority": priority,
            },
        },
        paths=paths,
    )
