from __future__ import annotations

import logging
from typing import List, Optional

from temporalio import activity

from .claude_agent import run_claude_agent
from .cccc_client import CCCCClient
from .config import get_config
from .graph import WorkflowState, run_planning_graph_async, notify_node_status

logger = logging.getLogger("workflow.activities")


PARSE_REQUIREMENTS_PROMPT = """分析以下用户需求，提取关键信息。

用户需求：
{request}

请用自然语言 Markdown 格式输出分析结果，格式如下：

## 📋 需求分析

**核心需求：**
（用一段话概括用户的核心需求）

**假设条件：**
- （列出你做出的假设，如果没有就写"暂无"）

**待澄清问题：**
- （列出需要用户确认的问题，如果没有就写"暂无"）

请直接输出 Markdown 内容，不要使用代码块包裹。"""


# CCCC peer prompt for brainstorming
CCCC_BRAINSTORM_PROMPT = """请帮我分析以下用户需求，进行头脑风暴：

用户需求：
{request}

请：
1. 识别核心需求和隐含需求
2. 提出关键问题帮助澄清
3. 列出可能的假设和风险
4. 给出初步的分析结论

以 Markdown 格式输出。"""


async def execute_with_cccc_peer(
    prompt: str,
    peer_id: str,
    command: Optional[str] = None,
    group_id: Optional[str] = None,
    timeout: float = 120.0,
) -> Optional[str]:
    """Execute a prompt using a CCCC peer.

    Args:
        prompt: The prompt to send
        peer_id: Target peer ID
        command: Optional command prefix (e.g., "/brainstorm")
        group_id: CCCC group ID
        timeout: Timeout in seconds

    Returns:
        Peer's response or None on failure
    """
    config = get_config()
    gid = group_id or config.cccc_group_id

    client = CCCCClient(group_id=gid)

    # Send message to peer
    text = f"{command} {prompt}" if command else prompt
    logger.info(f"Sending to CCCC peer {peer_id}: {text[:100]}...")

    send_resp = client.send_to_peer(peer_id=peer_id, text=text)
    if not send_resp.get("ok"):
        logger.error(f"Failed to send to peer: {send_resp.get('error')}")
        return None

    # Extract send timestamp to filter responses
    send_ts = send_resp.get("result", {}).get("event", {}).get("ts", "")
    logger.info(f"Message sent at {send_ts}, waiting for response...")

    # Wait for response (only messages after our send)
    response = await client.wait_for_response(
        from_peer=peer_id,
        after_ts=send_ts,
        timeout=timeout,
    )

    if response:
        logger.info(f"Received response from {peer_id}: {response[:100]}...")
    else:
        logger.warning(f"Timeout waiting for response from {peer_id}")

    return response


@activity.defn
async def parse_requirements(state: WorkflowState) -> WorkflowState:
    run_id = state.get("run_id", "")
    request = (state.get("request") or "").strip()

    # Notify: running
    await notify_node_status(run_id, "parse_requirements", "running")

    if not request:
        output = {
            "parsed_requirements": "（空需求）",
            "assumptions": [],
            "questions": ["请提供具体需求描述"],
        }
        await notify_node_status(run_id, "parse_requirements", "completed", output)
        return {**state, **output}

    # Get node configuration
    config = get_config()
    node_config = config.get_node_config("parse_requirements")

    # Execute based on configuration
    if node_config.executor == "cccc_peer" and node_config.peer_id:
        # Use CCCC peer
        logger.info(f"Using CCCC peer: {node_config.peer_id}")
        await notify_node_status(run_id, "parse_requirements", "waiting_peer", {
            "peer_id": node_config.peer_id,
            "command": node_config.command,
        })

        prompt = CCCC_BRAINSTORM_PROMPT.format(request=request)
        result = await execute_with_cccc_peer(
            prompt=prompt,
            peer_id=node_config.peer_id,
            command=node_config.command,
            timeout=node_config.timeout,
        )

        # Fallback to Claude CLI if CCCC fails
        if result is None:
            logger.warning("CCCC peer failed, falling back to Claude CLI")
            prompt = PARSE_REQUIREMENTS_PROMPT.format(request=request)
            result = await run_claude_agent(prompt)
    else:
        # Use Claude CLI
        prompt = PARSE_REQUIREMENTS_PROMPT.format(request=request)
        result = await run_claude_agent(prompt)

    # Output is now human-readable Markdown, use directly
    output = {
        "parsed_requirements": result,
        "assumptions": [],
        "questions": [],
    }

    # Notify: completed with Markdown output for display
    await notify_node_status(run_id, "parse_requirements", "completed", result)

    return {**state, **output}


@activity.defn
async def plan_review_dispatch(state: WorkflowState) -> WorkflowState:
    return await run_planning_graph_async(state)
