# 目标组任务执行指南

本指南面向**目标 CCCC Group 的 Foreman**，说明如何接收和执行来自批量 Bug 修复工作流的任务。

## 概述

批量 Bug 修复系统使用**轮询机制**分发任务：
- 源 Group 通过 API 创建批量任务
- 目标 Group 主动轮询获取分配的任务
- 任务执行状态通过 API 直接更新

## API 端点

### 1. 获取待处理任务

```
GET /api/v2/cccc/tasks?group_id={your_group_id}&status=pending
```

**参数：**
- `group_id` (必填): 你的 Group ID
- `status` (可选): 过滤条件
  - `pending` (默认): 只返回待处理任务
  - `in_progress`: 只返回进行中任务
  - `all`: 返回所有任务

**响应示例：**
```json
{
  "tasks": [
    {
      "job_id": "job_abc123def456",
      "bug_index": 0,
      "url": "https://jira.example.com/browse/BUG-123",
      "status": "pending",
      "config": {
        "validation_level": "standard",
        "failure_policy": "skip",
        "max_retries": 3
      }
    }
  ],
  "total": 1
}
```

### 2. 更新任务状态

```
POST /api/v2/cccc/tasks/{job_id}/bugs/{bug_index}/status
```

**请求体：**
```json
{
  "status": "in_progress",  // 或 "completed", "failed", "skipped"
  "error": null             // 可选，失败时填写错误信息
}
```

**状态值：**
- `in_progress`: 开始处理
- `completed`: 修复成功
- `failed`: 修复失败
- `skipped`: 跳过（根据 failure_policy）

**响应示例：**
```json
{
  "success": true,
  "job_id": "job_abc123def456",
  "bug_index": 0,
  "new_status": "completed",
  "job_status": "running"
}
```

## 执行流程

### 步骤 1: 轮询获取任务

```python
# 建议每 30 秒轮询一次
import requests

BASE_URL = "http://localhost:8000"
MY_GROUP_ID = "g_your_group_id"

def poll_tasks():
    resp = requests.get(
        f"{BASE_URL}/api/v2/cccc/tasks",
        params={"group_id": MY_GROUP_ID, "status": "pending"}
    )
    return resp.json()["tasks"]
```

### 步骤 2: 认领任务

获取到任务后，立即更新状态为 `in_progress`：

```python
def claim_task(job_id: str, bug_index: int):
    resp = requests.post(
        f"{BASE_URL}/api/v2/cccc/tasks/{job_id}/bugs/{bug_index}/status",
        json={"status": "in_progress"}
    )
    return resp.json()["success"]
```

### 步骤 3: 执行 Bug 修复

根据任务的 `url` 和 `config` 执行修复：

```python
def execute_bug_fix(task: dict):
    url = task["url"]
    config = task["config"]

    # 1. 获取 Bug 详情（通过 Jira MCP 或 API）
    # 2. 分析问题
    # 3. 实施修复
    # 4. 验证修复（根据 validation_level）

    return {"success": True, "error": None}
```

### 步骤 4: 报告结果

```python
def report_result(job_id: str, bug_index: int, success: bool, error: str = None):
    status = "completed" if success else "failed"
    resp = requests.post(
        f"{BASE_URL}/api/v2/cccc/tasks/{job_id}/bugs/{bug_index}/status",
        json={"status": status, "error": error}
    )
    return resp.json()
```

## 完整执行循环示例

```python
import time

def task_execution_loop():
    while True:
        tasks = poll_tasks()

        if not tasks:
            time.sleep(30)  # 无任务时等待
            continue

        for task in tasks:
            job_id = task["job_id"]
            bug_index = task["bug_index"]

            # 认领任务
            if not claim_task(job_id, bug_index):
                continue

            # 执行修复
            result = execute_bug_fix(task)

            # 报告结果
            report_result(
                job_id,
                bug_index,
                result["success"],
                result.get("error")
            )

        time.sleep(5)  # 处理完一批后短暂等待
```

## 配置说明

任务的 `config` 字段包含执行策略：

| 字段 | 说明 | 可选值 |
|------|------|--------|
| `validation_level` | 验证级别 | `minimal`, `standard`, `thorough` |
| `failure_policy` | 失败处理 | `stop`, `skip`, `retry` |
| `max_retries` | 最大重试次数 | 1-10 |

### 验证级别

- **minimal**: 基本语法检查
- **standard**: 语法 + 单元测试
- **thorough**: 语法 + 单元测试 + 集成测试

### 失败策略

- **stop**: 遇到失败立即停止
- **skip**: 跳过失败的任务继续下一个
- **retry**: 重试直到 max_retries 次

## 注意事项

1. **幂等性**: 认领任务前检查状态，避免重复处理
2. **超时处理**: 长时间 `in_progress` 的任务可能需要手动干预
3. **错误记录**: 失败时务必填写 `error` 字段便于追踪
4. **轮询间隔**: 建议 30 秒，避免过于频繁

## 与 CCCC 集成

在 CCCC Group 中，Foreman 可以：

1. **自动轮询**: 在 session 启动时设置定时任务
2. **分配给 Peers**: 将获取的任务分配给专门的 peer 执行
3. **汇报进度**: 通过 `cccc_message_send` 向源 Group 汇报整体进度

```python
# 示例：Foreman 分配任务给 peer
cccc_message_send(
    to=["bug-fixer-peer"],
    text=f"请处理以下 Bug: {task['url']}\n验证级别: {task['config']['validation_level']}"
)
```

---

*文档版本: 1.0 | 更新时间: 2026-02-05*
