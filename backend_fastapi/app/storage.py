from __future__ import annotations

from typing import Dict, List
from uuid import uuid4

from .models import (
    WorkflowDetail,
    WorkflowLog,
    WorkflowParameters,
    RunRecord,
    now_iso,
)

WORKFLOWS: List[WorkflowDetail] = [
    WorkflowDetail(
        id="wf-001",
        name="发布构建流程",
        status="running",
        version="v1.2",
        created_at=now_iso(),
        updated_at=now_iso(),
        parameters=WorkflowParameters(
            trigger="张三", priority="normal", schedule="2026-01-24 10:00", notifyBot=True
        ),
        nodeConfig="描述该节点的输入、输出与重试策略",
    )
]

RUNS: Dict[str, List[RunRecord]] = {
    "wf-001": [
        RunRecord(
            id="run-001",
            workflowId="wf-001",
            status="running",
            started_at=now_iso(),
            ended_at=None,
            triggered_by="张三",
        )
    ]
}

LOGS: Dict[str, List[WorkflowLog]] = {
    "wf-001": [
        WorkflowLog(
            id=str(uuid4()),
            runId="run-001",
            time=now_iso(),
            level="info",
            message="启动运行",
            source="worker",
        )
    ]
}
