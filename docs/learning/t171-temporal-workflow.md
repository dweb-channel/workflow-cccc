# Temporal 持久化工作流实战

> 基于 work-flow 项目真实代码，讲解 Temporal 的 Workflow/Activity 模式、超时策略、心跳机制、状态同步架构，以及与 CCCC 多 Agent 系统的架构对比。

---

## 目录

- [S1: Temporal 核心概念](#s1-temporal-核心概念)
  - [1.1 为什么需要 Temporal](#11-为什么需要-temporal)
  - [1.2 Workflow vs Activity：职责分离](#12-workflow-vs-activity职责分离)
  - [1.3 Worker 注册与启动](#13-worker-注册与启动)
  - [1.4 客户端适配器：FastAPI 如何启动工作流](#14-客户端适配器fastapi-如何启动工作流)
  - [1.5 架构对比：work-flow vs CCCC](#15-架构对比work-flow-vs-cccc)
- [S2: 超时策略设计](#s2-超时策略设计)
  - [2.1 三层超时模型](#21-三层超时模型)
  - [2.2 Batch Bug Fix 超时计算](#22-batch-bug-fix-超时计算)
  - [2.3 Design-to-Spec 超时计算](#23-design-to-spec-超时计算)
  - [2.4 Dynamic Workflow 超时计算](#24-dynamic-workflow-超时计算)
  - [2.5 超时设置外部化](#25-超时设置外部化)
- [S3: Activity 实战模式](#s3-activity-实战模式)
  - [3.1 心跳上报：防止 Temporal 误判超时](#31-心跳上报防止-temporal-误判超时)
  - [3.2 SSE 事件推送：Worker → FastAPI → 前端](#32-sse-事件推送worker--fastapi--前端)
  - [3.3 状态同步：Worker → DB → SSE 三级传播链](#33-状态同步worker--db--sse-三级传播链)
  - [3.4 断点恢复：Checkpoint 机制](#34-断点恢复checkpoint-机制)
  - [3.5 取消处理与资源清理](#35-取消处理与资源清理)
  - [3.6 Git 隔离：每个 Bug 独立提交/回滚](#36-git-隔离每个-bug-独立提交回滚)
  - [3.7 重试与指数退避](#37-重试与指数退避)
- [S4: 动手练习](#s4-动手练习)
- [关键文件索引](#关键文件索引)

---

## S1: Temporal 核心概念

### 1.1 为什么需要 Temporal

在 M10 之前，项目用 `asyncio.create_task()` 在 FastAPI 进程内直接执行工作流：

```
FastAPI (单进程)
  └─ asyncio.create_task(workflow)
       └─ stream_claude_events() 紧密循环
            └─ readline() 不 yield → 事件循环饥饿 → 页面冻结
```

中间尝试过 `await asyncio.sleep(0)` 强制让出控制，但这只是治标不治本。根本问题是：**CPU/IO 密集任务和 HTTP 服务共享同一个事件循环**。

我们考虑过几种方案：

| 方案 | 优点 | 缺点 |
|------|------|------|
| asyncio + sleep(0) | 最简单 | 治标不治本，大 buffer 仍卡 |
| Celery | 成熟稳定 | 需要 Redis/RabbitMQ，不支持工作流编排 |
| 原生多进程 | 无依赖 | 自己造轮子：重试、超时、持久化 |
| **Temporal** | 持久化执行、自带重试/超时/心跳 | 多一个基础设施依赖 |

最终选择 Temporal，因为它**同时解决了三个问题**：
1. **进程隔离** — Worker 是独立进程，阻塞不影响 FastAPI
2. **持久化执行** — Temporal Server 持久化工作流状态，Worker 崩溃可恢复
3. **生产级可靠性** — 内置重试策略、超时检测、心跳监控，不需要自己实现

### 1.2 Workflow vs Activity：职责分离

Temporal 的核心设计模式是 **Workflow 编排 + Activity 执行**：

```
Workflow（极简编排层）：
  - 决定做什么、按什么顺序做
  - 不做具体工作，只调度 Activity
  - 必须是确定性代码（不能有随机、当前时间、IO）
  - 被 Temporal Server 持久化，崩溃可恢复

Activity（重实现层）：
  - 做具体工作（调 Claude CLI、读写 DB、推 SSE 事件）
  - 可以做任何 IO 操作
  - 不需要确定性
  - 失败后由 Workflow 控制重试
```

项目中的三对 Workflow/Activity：

| Workflow | Activity | 代码量 | 职责 |
|----------|----------|--------|------|
| `DynamicWorkflow` (64 行) | `execute_dynamic_graph_activity` (62 行) | **极简** | 通用动态图执行 |
| `BatchBugFixWorkflow` (62 行) | `execute_batch_bugfix_activity` (585 行) | **重** | 批量 Bug 修复 |
| `SpecPipelineWorkflow` (68 行) | `execute_spec_pipeline_activity` (605 行) | **重** | Design-to-Spec |

注意代码量对比：**Workflow 60 行 vs Activity 600 行**。这就是"编排层极简、执行层重"的设计哲学。

> **两条管线的内部引擎差异**：BatchBugFixWorkflow 的 Activity 内部使用 T170 讲解的 LangGraph 引擎执行循环工作流（`_execute_workflow()` → `build_graph_from_config()` → `astream`，见 `batch_activities.py:268`），而 SpecPipelineWorkflow 的 Activity 手动序列化 4 个 Phase（Figma 获取 → 分解 → LLM 分析 → 组装），不经过 LangGraph 图执行器。前者适合结构可变的动态工作流，后者适合固定步骤的线性管线。

以 `BatchBugFixWorkflow` 为例（`batch_workflow.py` 全文仅 62 行）：

```python
@workflow.defn
class BatchBugFixWorkflow:
    def __init__(self) -> None:
        self._result: dict = {}

    @workflow.run
    async def run(self, params: dict) -> dict:
        bug_count = len(params.get("jira_urls", []))
        timeout_minutes = max(
            BATCH_WORKFLOW_MIN_TIMEOUT_MINUTES,      # 30 分钟下限
            bug_count * BATCH_WORKFLOW_PER_BUG_MINUTES,  # 每 Bug 15 分钟
        )

        self._result = await workflow.execute_activity(
            execute_batch_bugfix_activity,
            params,
            schedule_to_close_timeout=timedelta(minutes=timeout_minutes),
            heartbeat_timeout=timedelta(minutes=BATCH_WORKFLOW_HEARTBEAT_TIMEOUT_MINUTES),
        )
        return self._result

    @workflow.query
    def get_result(self) -> dict:
        return self._result
```

Workflow 只做了三件事：
1. **计算超时** — 基于 Bug 数量动态调整
2. **调度 Activity** — `workflow.execute_activity()` 把活交给 Worker
3. **暴露查询** — `@workflow.query` 让外部可以查询中间结果

所有具体工作（调 Claude CLI、推 SSE、写 DB）都在 Activity 里。

### 1.3 Worker 注册与启动

> 源码：`temporal/worker.py`（32 行）

Worker 是一个独立进程，向 Temporal Server 注册自己能处理的 Workflow 和 Activity：

```python
async def main() -> None:
    client = await Client.connect(TEMPORAL_ADDRESS)
    worker = Worker(
        client,
        task_queue=TASK_QUEUE,
        workflows=[DynamicWorkflow, BatchBugFixWorkflow, SpecPipelineWorkflow],
        activities=[
            execute_dynamic_graph_activity,
            execute_batch_bugfix_activity,
            execute_spec_pipeline_activity,
        ],
    )
    await worker.run()
```

**关键概念 — Task Queue**：
- Temporal 通过 Task Queue 匹配 Workflow/Activity 和 Worker
- 一个 Worker 可以注册多个 Workflow 和 Activity
- 多个 Worker 可以监听同一个 Task Queue（负载均衡）
- 项目中只有一个 Task Queue（`business-workflow-task-queue`，见 `config.py:12`），一个 Worker 处理所有任务

**启动命令**：

```bash
# 方式 1：直接运行
python -m workflow.temporal.worker

# 方式 2：通过 Makefile
make dev  # 同时启动 FastAPI + Worker + Temporal
```

### 1.4 客户端适配器：FastAPI 如何启动工作流

> 源码：`app/temporal_adapter.py`（132 行）

FastAPI 通过 `temporal_adapter` 模块与 Temporal Server 通信：

```python
# 单例模式：整个 FastAPI 进程只有一个 Temporal 客户端
_client: Optional[Client] = None
_client_lock = asyncio.Lock()

async def get_client() -> Client:
    global _client
    if _client is None:
        await init_temporal_client()
    if _client is None:
        raise RuntimeError("Temporal 未连接，请先启动 Temporal 服务")
    return _client
```

启动工作流的函数：

```python
async def start_spec_pipeline(
    job_id: str, file_key: str, node_id: str,
    output_dir: str, model: str = "",
    component_count_estimate: int = 3,
) -> str:
    client = await get_client()
    workflow_id = f"spec-{job_id}"
    await client.start_workflow(
        "SpecPipelineWorkflow",
        params,
        id=workflow_id,                    # 幂等：同 ID 不会重复创建
        task_queue=TEMPORAL_TASK_QUEUE,
    )
    return workflow_id
```

**优雅降级**：当 Temporal Server 不可用时，`init_temporal_client()` 不会崩溃，而是记录 warning 返回 None。后续调用 `get_client()` 会抛出 `RuntimeError`，API 层返回 503。其他不依赖 Temporal 的接口正常工作。

### 1.5 架构对比：work-flow vs CCCC

用户观察到 CCCC 和 work-flow 有很强的架构相似性。让我们做一个深入对比：

```
work-flow 架构：
  FastAPI (:8000)                    ← HTTP 入口
    └─ temporal_adapter               ← 启动工作流
         └─ Temporal Server           ← 持久化编排
              └─ Worker (独立进程)     ← 执行 Activity
                   └─ Claude CLI       ← AI 调用
                   └─ HTTP POST → FastAPI  ← SSE 事件回传

CCCC 架构：
  uvicorn Web (:8848)                ← HTTP 入口
    └─ Unix Socket                    ← 和 Daemon 通信
         └─ Daemon (ccccd)            ← 进程管理 + 消息路由
              └─ Agent PTY (独立进程)  ← 执行任务
                   └─ MCP 工具         ← 和 Daemon 通信
```

| 维度 | work-flow | CCCC |
|------|-----------|------|
| **编排器** | Temporal Server（外部服务） | Daemon（内嵌进程） |
| **执行器** | Worker Activity | Agent PTY |
| **通信协议** | HTTP POST（事件回传） | MCP + Unix Socket |
| **持久化** | Temporal 历史 + SQLite | Ledger 事件日志 |
| **失败恢复** | Activity 重试 + 心跳超时检测 | Agent 重启 + context 恢复 |
| **超时管理** | 三层超时（schedule/start/heartbeat） | 内置 silence_check + keepalive |

**核心设计理念一致**：
1. **进程隔离** — 重活放独立进程，HTTP 服务不受阻塞
2. **事件驱动** — 异步消息通信，非同步阻塞调用
3. **编排 vs 执行分离** — 调度层轻量、执行层重

**关键差异**：Temporal 提供**持久化执行保证** — Worker 崩溃后，Temporal Server 会重新调度 Activity 到另一个 Worker。CCCC 的 Agent 重启需要从 Context 手动恢复。这就是为什么 Temporal 更适合"长时间、不能丢"的任务。

---

## S2: 超时策略设计

### 2.1 三层超时模型

Temporal 提供三种超时机制，从外到内：

```
┌───────────────────────────────────────────────────┐
│  schedule_to_close_timeout                        │
│  从 Activity 被调度到完成的总时限                     │
│                                                   │
│  ┌───────────────────────────────────────────┐   │
│  │  start_to_close_timeout                    │   │
│  │  从 Activity 开始执行到完成的时限             │   │
│  │  （不含排队等待时间）                        │   │
│  │                                           │   │
│  │  ┌───────────────────────────────┐       │   │
│  │  │  heartbeat_timeout             │       │   │
│  │  │  两次心跳之间的最大间隔          │       │   │
│  │  │  超时 = Worker 可能已死          │       │   │
│  │  └───────────────────────────────┘       │   │
│  └───────────────────────────────────────────┘   │
└───────────────────────────────────────────────────┘
```

项目中的使用方式：

| 管线 | schedule_to_close | heartbeat_timeout | start_to_close |
|------|-------------------|-------------------|----------------|
| Batch Bug Fix | `max(30, N×15)` 分钟 | 15 分钟 | 未设置（用 schedule） |
| Design-to-Spec | `max(15, N×10+5)` 分钟 | 10 分钟 | 未设置 |
| Dynamic Workflow | `max(10, N×5) × iter` 分钟 | 未设置 | 未设置 |

为什么 `heartbeat_timeout < schedule_to_close`？因为两者检测的是不同的故障模式：
- **schedule_to_close** — 任务整体是否超时（正常的慢 vs 确实卡死）
- **heartbeat_timeout** — Worker 进程是否还活着（比如被 OOM Killer 杀了）

### 2.2 Batch Bug Fix 超时计算

> 源码：`batch_workflow.py:44-48`

```python
bug_count = len(params.get("jira_urls", []))
timeout_minutes = max(
    BATCH_WORKFLOW_MIN_TIMEOUT_MINUTES,      # 默认 30 分钟
    bug_count * BATCH_WORKFLOW_PER_BUG_MINUTES,  # 每 Bug 15 分钟
)
```

**计算逻辑**：
- 1 个 Bug → `max(30, 1×15)` = **30 分钟**（保底下限）
- 3 个 Bug → `max(30, 3×15)` = **45 分钟**
- 10 个 Bug → `max(30, 10×15)` = **150 分钟**

为什么每 Bug 15 分钟？因为一个 Bug 的完整修复链路（获取信息 → Claude 修复 → Claude 验证 → 可能重试）通常在 5-10 分钟内完成，15 分钟留了 50% 的安全余量。

### 2.3 Design-to-Spec 超时计算

> 源码：`spec_workflow.py:49-54`

```python
component_count = params.get("component_count_estimate", 3)
timeout_minutes = max(
    SPEC_WORKFLOW_MIN_TIMEOUT_MINUTES,           # 默认 15 分钟
    component_count * SPEC_WORKFLOW_PER_COMPONENT_MINUTES  # 每组件 10 分钟
    + SPEC_WORKFLOW_OVERHEAD_MINUTES,             # 固定开销 5 分钟
)
```

这里有一个 **phase-aware** 的设计思考：

```
Phase 1 Figma Fetch:     ~30 秒（快，固定开销）
Phase 2 FrameDecomposer: ~1 秒（极快，纯 Python）
Phase 3 SpecAnalyzer:    ~3-8 分钟/组件（慢，涉及 LLM）
Phase 4 SpecAssembler:   ~1 秒（快）
```

耗时主要集中在 Phase 3（LLM 视觉分析），所以超时公式以**组件数量**为核心变量。`OVERHEAD_MINUTES=5` 覆盖了 Phase 1/2/4 的开销。

### 2.4 Dynamic Workflow 超时计算

> 源码：`workflows.py:42-49`

```python
node_count = len(wf_def.get("nodes", []))
max_iterations = wf_def.get("max_iterations", 10)
base_timeout = max(10, node_count * 5)  # 每节点 5 分钟
# 如果有循环，按 max_iterations 放大
timeout_minutes = (
    base_timeout * max(1, max_iterations // 5 + 1)
    if max_iterations > 1
    else base_timeout
)
```

**循环放大因子**：当 `max_iterations > 1` 时，说明图中可能有循环。每 5 次迭代算 1 倍基础超时。例如：

- 10 节点、无循环 → `max(10, 10×5)` = **50 分钟**
- 10 节点、max_iterations=20 → `50 × (20//5+1)` = `50 × 5` = **250 分钟**

### 2.5 超时设置外部化

> 源码：`settings.py:47-68`

所有超时参数都通过环境变量外部化，有合理的默认值：

```python
# Design-to-Spec 超时
SPEC_HEARTBEAT_INTERVAL = _float("SPEC_HEARTBEAT_INTERVAL", 60.0)        # 心跳间隔 60 秒
SPEC_WORKFLOW_MIN_TIMEOUT_MINUTES = _int("SPEC_WORKFLOW_MIN_TIMEOUT_MINUTES", 15)
SPEC_WORKFLOW_PER_COMPONENT_MINUTES = _int("SPEC_WORKFLOW_PER_COMPONENT_MINUTES", 10)
SPEC_WORKFLOW_OVERHEAD_MINUTES = _int("SPEC_WORKFLOW_OVERHEAD_MINUTES", 5)
SPEC_WORKFLOW_HEARTBEAT_TIMEOUT_MINUTES = _int("SPEC_WORKFLOW_HEARTBEAT_TIMEOUT_MINUTES", 10)

# Batch Bug Fix 超时
BATCH_HEARTBEAT_INTERVAL = _float("BATCH_HEARTBEAT_INTERVAL", 60.0)       # 心跳间隔 60 秒
BATCH_WORKFLOW_MIN_TIMEOUT_MINUTES = _int("BATCH_WORKFLOW_MIN_TIMEOUT_MINUTES", 30)
BATCH_WORKFLOW_PER_BUG_MINUTES = _int("BATCH_WORKFLOW_PER_BUG_MINUTES", 15)
BATCH_WORKFLOW_HEARTBEAT_TIMEOUT_MINUTES = _int("BATCH_WORKFLOW_HEARTBEAT_TIMEOUT_MINUTES", 15)
```

**为什么外部化？** 不同环境（开发 vs 生产）的超时需求不同。开发时 Claude CLI 可能因 rate limit 变慢，需要更长的超时。通过环境变量调整，不需要改代码重新部署。

---

## S3: Activity 实战模式

### 3.1 心跳上报：防止 Temporal 误判超时

> 源码：`sse_events.py:69-81`（通用心跳）+ `batch_activities.py:197-201, 257-262`（使用方）

**问题**：一次 Claude CLI 调用可能耗时 3-5 分钟（复杂 Bug 修复）。如果 `heartbeat_timeout=15min` 且 Activity 在 15 分钟内没发心跳，Temporal 会认为 Worker 死了，强制取消并重试。

**解决方案**：后台心跳任务

```python
# sse_events.py:69-81
async def _periodic_heartbeat(job_id: str, interval_seconds: int = 60) -> None:
    """在后台每 60 秒发一次心跳，防止 Temporal 超时。"""
    while True:
        await asyncio.sleep(interval_seconds)
        try:
            activity.heartbeat(f"alive:job:{job_id}")
        except Exception:
            # Activity 可能已完成或被取消，停止心跳
            return
```

**使用方式**：

```python
# batch_activities.py:199-201 — 启动心跳后台任务
heartbeat_task = asyncio.create_task(
    _periodic_heartbeat(job_id, interval_seconds=60)
)

# ... 执行实际工作 ...

# batch_activities.py:257-262 — 无论成功失败，最后清理心跳
finally:
    heartbeat_task.cancel()
    try:
        await heartbeat_task
    except asyncio.CancelledError:
        pass
```

**注意**：项目中有两个 `_periodic_heartbeat` 实现：
- **`sse_events.py:69-81`** — 被 `batch_activities.py` 导入使用（L25），心跳消息 `f"alive:job:{job_id}"`，间隔硬编码 60 秒
- **`spec_activities.py:136-143`** — 独立实现，心跳消息 `f"keepalive:{job_id}"`，使用 `SPEC_HEARTBEAT_INTERVAL` 配置（settings.py），而非硬编码

两者功能相同（后台定期发 Temporal 心跳），但消息格式不同。Spec 管线之所以独立实现，是因为它需要可配置的心跳间隔以适应不同规模的设计文件分析。

**两层心跳策略**：

1. **定期心跳**（`_periodic_heartbeat`）— 后台定期发送，确保 Temporal 知道 Worker 还活着
2. **语义心跳**（`activity.heartbeat("phase:figma_fetch_done")`）— 在每个关键节点后发送，携带进度信息

```python
# spec_activities.py 中的语义心跳
activity.heartbeat("phase:init")              # 初始化完成
activity.heartbeat("phase:figma_fetch_done")  # Figma 数据获取完成
activity.heartbeat("phase:decompose_done")    # 结构提取完成
activity.heartbeat(f"phase:analyze_done:{completed}/{total}")  # 分析进度
activity.heartbeat("phase:complete")          # 全部完成

# batch_activities.py 中的语义心跳
activity.heartbeat(f"node:{node_id}:bug:{bug_index}")  # 每个节点完成后
```

语义心跳虽然不影响超时判断，但在 Temporal Web UI 中可以看到最后一次心跳的内容，方便调试"卡在哪个阶段"。

### 3.2 SSE 事件推送：Worker → FastAPI → 前端

> 源码：`sse_events.py:36-66`

**问题**：Worker 是独立进程，没有 FastAPI 的 `EventBus` 实例。怎么把事件推给前端？

**方案**：Worker 通过 **HTTP POST** 把事件推给 FastAPI 的内部端点：

```python
# sse_events.py:36-48 — 非阻塞推送
async def _push_event(job_id: str, event_type: str, data: Dict) -> None:
    """通过 HTTP POST 推送 SSE 事件到 FastAPI。"""
    from ..sse import push_sse_event  # 封装了 POST /api/internal/events/{job_id}
    try:
        await push_sse_event(job_id, event_type, data)
    except Exception as e:
        logger.error(f"Job {job_id}: Failed to push SSE event {event_type}: {e}")
        # 注意：推送失败不中断工作流！事件丢失 < 任务失败
```

**关键设计决策**：`_push_event` **永不抛异常**。SSE 事件是"尽力而为"的——丢一条事件不影响最终结果，但让工作流因为推送失败而中断就太不划算了。

**同步回调桥接**（`sse_events.py:51-66`）：

Claude CLI 的 `on_event` 回调是**同步**的（详见 T165），但 HTTP POST 是异步操作。怎么桥接？

```python
def _setup_sync_event_pusher() -> None:
    """把同步回调桥接到异步 HTTP POST。"""
    def sync_push(job_id: str, event_type: str, data: Dict) -> None:
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(_push_event(job_id, event_type, data))  # fire-and-forget
        except RuntimeError:
            pass  # 没有事件循环，跳过
    set_job_event_pusher(sync_push)
```

`loop.create_task()` 是"发射并遗忘"模式 — 把异步 POST 丢到事件循环里，不等它完成。这样同步回调不会阻塞 Claude CLI 的 stdout 读取。

### 3.3 状态同步：Worker → DB → SSE 三级传播链

> 源码：`state_sync.py`（329 行）

状态同步是最复杂的部分。让我们看完整的传播链：

```
Worker Activity 内部状态
       │
       │  _sync_incremental_results()  ← 每完成一个 Bug
       │  _sync_final_results()        ← 任务结束时
       ▼
  SQLite 数据库 (BatchJob / BugResult)
       │
       │  _push_event()
       ▼
  FastAPI EventBus → SSE → 前端
```

**增量同步**（`state_sync.py:149-228`）：

每完成一个 Bug，立即同步到 DB 和 SSE：

```python
async def _sync_incremental_results(
    job_id, jira_urls, results, start_index,
    bug_index_offset=0, index_map=None,
):
    for i in range(start_index, len(results)):
        db_i = _db_index(i, bug_index_offset, index_map)
        result = results[i]

        # 1. 推送 SSE 事件
        if result_status == "completed":
            await _push_event(job_id, "bug_completed", {...})
        elif result_status == "failed":
            await _push_event(job_id, "bug_failed", {...})

        # 2. 更新 DB
        await _update_bug_status_db(job_id, db_i, result_status, ...)

    # 3. 标记下一个 Bug 为 in_progress
    if next_index < len(jira_urls):
        await _update_bug_status_db(job_id, db_next, "in_progress", ...)
        await _push_event(job_id, "bug_started", {...})
```

**索引映射**（state_sync.py:20-32）—— 一个容易出错的细节：

```python
def _db_index(bug_index, bug_index_offset, index_map=None):
    """将工作流内部索引映射到 DB/SSE 的 bug_index。"""
    if index_map is not None:
        return index_map[bug_index]  # 跳过模式
    return bug_index + bug_index_offset  # 重试模式
```

为什么需要索引映射？两个场景：
- **Pre-scan 跳过**：预扫描发现 Bug #1、#3 已关闭，实际只处理 #0、#2、#4。工作流内部的 index 0→DB index 0，内部 index 1→DB index 2，内部 index 2→DB index 4
- **单 Bug 重试**：只重试 Bug #3，`bug_index_offset=3`，工作流内部 index 0→DB index 3

**最终同步**（`state_sync.py:231-329`）—— 带重试的原子性保证：

```python
async def _sync_final_results(job_id, final_state, jira_urls, ...):
    results = final_state.get("results", [])
    completed = sum(1 for r in results if r.get("status") == "completed")
    failed = sum(1 for r in results if r.get("status") == "failed")
    skipped = sum(1 for r in results if r.get("status") == "skipped")

    # 初始判定：failed 和 skipped 都为 0 才算 completed
    overall = "completed" if failed == 0 and skipped == 0 else "failed"

    for attempt in range(BATCH_DB_SYNC_MAX_ATTEMPTS):  # 默认 4 次
        try:
            async with get_session_ctx() as session:
                for i, result in enumerate(results):
                    await repo.update_bug_status(...)

                # 重试/跳过模式：从 DB 全量 Bug 重新计算
                if bug_index_offset > 0 or index_map is not None:
                    if index_map is not None:
                        # Skip 模式：pre-scan 跳过的 Bug 不算失败
                        all_failed = sum(1 for b in db_bugs if b.status == "failed")
                    else:
                        # Retry 模式：skipped 也算失败（原始行为）
                        all_failed = sum(1 for b in db_bugs if b.status in ("failed", "skipped"))
                    overall = "completed" if all_failed == 0 else "failed"

                await repo.update_status(job_id, overall)
            break  # 成功，退出重试
        except Exception:
            # 指数退避：1s, 2s, 4s + ±25% 抖动
            delay = (2 ** attempt) * (1.0 + random.uniform(-0.25, 0.25))
            await asyncio.sleep(delay)
```

> **注意**：`overall` 的判定在 Skip 模式和 Retry 模式下不同。Skip 模式下，pre-scan 已关闭的 Bug 被跳过（`status="skipped"`），不计入失败；Retry 模式下，`skipped` 状态视同失败。见 `state_sync.py:283-298`。

为什么最终同步需要重试？因为 SQLite 在并发写入时可能出现 `database is locked`。4 次重试 + 指数退避基本能解决。

### 3.4 断点恢复：Checkpoint 机制

> 源码：`spec_activities.py:92-129`

Design-to-Spec 管线中，Phase 3（SpecAnalyzer）是最慢的阶段。如果分析到第 5 个组件时 Worker 崩溃，Temporal 会重新调度 Activity。没有断点恢复的话，前 4 个组件要重新分析。

**Checkpoint 设计**：

```python
# 保存：每个组件分析完成后
def _save_checkpoint(output_dir, component_id, data):
    cp_dir = os.path.join(output_dir, ".spec_checkpoints")
    os.makedirs(cp_dir, exist_ok=True)
    path = os.path.join(cp_dir, f"{safe_id}.json")
    with open(path, "w") as f:
        json.dump(data, f, ensure_ascii=False)

# 加载：Activity 重新执行时
def _load_checkpoints(output_dir):
    cp_dir = os.path.join(output_dir, ".spec_checkpoints")
    result = {}
    for filename in os.listdir(cp_dir):
        data = json.load(open(path))
        result[data["id"]] = data
    return result
```

**恢复逻辑**（`spec_activities.py:363-397`）：

```python
checkpoints = _load_checkpoints(output_dir)
pre_completed = []
pending_components = []

for comp in components:
    comp_id = comp.get("id", "")
    if comp_id in checkpoints:
        cp_data = checkpoints[comp_id]
        # 验证 checkpoint 质量：role 不能是占位符
        if cp_data.get("role") and cp_data.get("role") != "other":
            pre_completed.append(cp_data)
            continue
    pending_components.append(comp)  # 需要重新分析
```

**检查点质量验证**：不是所有 checkpoint 都可信。如果 `role == "other"`，说明之前的分析可能失败了（fallback 值），需要重新分析。

### 3.5 取消处理与资源清理

> 源码：`batch_activities.py:229-262` + `spec_activities.py:553-595`

当用户在前端点"取消"时，Temporal 会向 Activity 发送 `CancelledError`：

```python
# batch_activities.py:229-262
try:
    final_state = await _execute_workflow(...)
    await _sync_final_results(...)
    return {"success": True, ...}

except asyncio.CancelledError:
    # 1. 记录日志
    logger.info(f"Job {job_id}: Activity cancelled")

    # 2. 清理 Git 状态（回滚未提交的修改）
    if await _git_is_repo(cwd):
        if await _git_has_changes(cwd):
            await _git_revert_changes(cwd, job_id, "cancelled")

    # 3. 更新 DB 状态
    await _update_job_status(job_id, "cancelled")

    # 4. 推送 SSE 通知前端
    await _push_event(job_id, "job_done", {"status": "cancelled", ...})
    return {"success": False, "cancelled": True}

except Exception as e:
    # 同样的清理逻辑，但状态是 "failed"
    ...

finally:
    # 无论如何都要停止心跳后台任务
    heartbeat_task.cancel()
```

**spec_activities.py 的 finally 安全网**（第 587-595 行）：

```python
finally:
    heartbeat_task.cancel()
    # 确保 DB 不会卡在 "running" 状态
    if final_status not in ("completed", "failed", "cancelled"):
        final_status = "failed"
        await _update_job_status(job_id, "failed", error="Pipeline interrupted unexpectedly")
    # 始终推送 job_done 事件
    if final_status != "cancelled":
        await _push_event(job_id, "job_done", {...})
```

这个 `finally` 块是最后的安全网。无论什么异常（甚至 `BaseException`），都确保：
1. 心跳停止
2. DB 状态不会永远卡在 `running`
3. 前端能收到 `job_done` 事件

### 3.6 Git 隔离：每个 Bug 独立提交/回滚

> 源码：`batch_activities.py:522-582`

Batch Bug Fix 中，每个 Bug 的修改需要独立隔离：

```
Bug #0 修复成功 → git commit "fix: PROJ-101"
Bug #1 修复成功 → git commit "fix: PROJ-102"
Bug #2 修复失败 → git revert（回滚所有未提交修改）
Bug #3 修复成功 → git commit "fix: PROJ-104"
```

实现方式（`batch_activities.py:522-577`）：

```python
# 修复成功 → 提交
if git_enabled and node_id == "update_success":
    change_summary = await _git_change_summary(cwd, job_id)
    if change_summary:
        # 推送变更摘要 SSE 事件
        await _push_event(job_id, "bug_step_completed", {
            "step": "code_summary",
            "output_preview": f"{files_changed} 文件变更 (+{insertions} -{deletions})",
        })
    # 提交
    committed = await _git_commit_bug_fix(cwd, bug_url, job_id)

# 修复失败 → 回滚
elif git_enabled and node_id == "update_failure":
    reverted = await _git_revert_changes(cwd, job_id, jira_key)
```

**最终安全网**（`batch_activities.py:579-582`）：

```python
# 工作流结束后，如果还有未提交的修改，全部回滚
if git_enabled and await _git_has_changes(cwd):
    logger.warning(f"Job {job_id}: Reverting leftover uncommitted changes")
    await _git_revert_changes(cwd, job_id, "cleanup")
```

### 3.7 重试与指数退避

Temporal 提供了 Activity 级别的自动重试，但项目中更细粒度的重试在 Activity 内部实现：

**1. Temporal 级重试**（Worker 崩溃时）：
- `activity.info().attempt` 返回当前是第几次尝试
- 重试时重置 stale bug 状态（`_reset_stale_bugs`）

```python
# batch_activities.py:126-129
attempt = activity.info().attempt
if attempt > 1:
    logger.info(f"Job {job_id}: Retry attempt {attempt}")
    await _reset_stale_bugs(job_id, len(jira_urls))
```

**2. DB 同步重试**（state_sync.py:257-312）：
- 最终同步失败时，指数退避重试 4 次
- 退避公式：`2^attempt × (1.0 ± 25% 抖动)` → 约 1s, 2s, 4s

**3. LLM 调用重试**（claude_cli_wrapper.py，详见 T165）：
- oneshot 模式：最多 3 次尝试，退避 10s, 20s
- rate limit 时：至少等 30 秒

**4. 单 Bug 内重试**（LangGraph 级别）：
- `check_retry` 条件节点 → `increment_retry` → 回到 `fix_bug_peer`
- 每次重试带上前次的 `verify_feedback`
- 由 `max_retries` 配置控制（默认 1 次重试）

**重试层级总结**：

```
Layer 1: Temporal（Worker 级）    — Worker 崩溃 → 整个 Activity 重新执行
Layer 2: DB 同步（操作级）        — SQLite locked → 指数退避 4 次
Layer 3: Claude CLI（调用级）     — Rate limit / 超时 → 指数退避 3 次
Layer 4: LangGraph（业务级）      — 验证失败 → 换思路重试修复
```

---

## S4: 动手练习

### 练习 1: 观察 Temporal Web UI

启动项目后，访问 Temporal Web UI（默认 `http://localhost:8233`）：

1. 触发一个 Batch Bug Fix 任务
2. 在 Temporal UI 中找到对应的 Workflow
3. 观察 Activity 的输入参数、心跳内容、执行时长
4. 尝试：手动终止 Worker 进程（`kill`），观察 Temporal 如何检测心跳超时并重新调度

### 练习 2: 分析超时公式

打开 `settings.py`，修改以下参数后重启 Worker：

```bash
SPEC_WORKFLOW_PER_COMPONENT_MINUTES=2  # 从 10 改为 2
SPEC_WORKFLOW_HEARTBEAT_TIMEOUT_MINUTES=3  # 从 10 改为 3
```

1. 触发一个 Design-to-Spec 任务（3 个组件）
2. 计算预期超时：`max(15, 3×2+5)` = 15 分钟
3. 问题：如果 Claude CLI 单个组件分析超过 3 分钟，会发生什么？（提示：心跳间隔 60s < heartbeat_timeout 3min，所以不会触发心跳超时。但如果心跳后台任务意外停止...）

### 练习 3: 走读状态同步

1. 打开 `state_sync.py`
2. 跟踪 `_sync_incremental_results()` 的完整执行路径
3. 问：如果 `_update_bug_status_db` 返回 False（DB 写入失败），会发生什么？（SSE 事件是否还能正常推送？最终同步会怎样？）
4. 模拟：在 `_update_bug_status_db` 中加一个 `raise Exception("test")`，观察 `db_sync_warning` SSE 事件

### 练习 4: 添加自定义心跳字段

在 `spec_activities.py` 的 Phase 3 循环中，给每个组件分析完成后发送一个更详细的心跳：

```python
activity.heartbeat(json.dumps({
    "phase": "analyze",
    "component": comp.get("suggested_name", "unknown"),
    "progress": f"{i+1}/{len(pending_components)}",
    "token_usage": token_usage,
}))
```

在 Temporal Web UI 中查看心跳详情，观察每个组件的分析进度和 token 消耗。

---

## 关键文件索引

```
backend/workflow/temporal/
├── worker.py              ← ★ Worker 启动入口（32 行）
├── workflows.py           ← ★ DynamicWorkflow 定义（64 行）
├── batch_workflow.py      ← ★ BatchBugFixWorkflow（62 行）
├── spec_workflow.py       ← ★ SpecPipelineWorkflow（68 行）
├── activities.py          ← 通用动态图 Activity（62 行）
├── batch_activities.py    ← ★ 批量修复 Activity（585 行）
├── spec_activities.py     ← ★ 设计管线 Activity（605 行）
├── state_sync.py          ← ★ DB 状态同步（329 行）
├── sse_events.py          ← SSE 推送 + 心跳（138 行）
└── git_operations.py      ← Git 操作封装（334 行）

backend/app/
├── temporal_adapter.py    ← ★ Temporal 客户端适配器（132 行）
└── event_bus.py           ← EventBus SSE 基础设施

backend/workflow/
├── settings.py            ← ★ 超时参数配置
└── sse.py                 ← push_sse_event HTTP POST 封装
```

> **★ = 建议优先阅读的文件**

---

> 作者: domain-expert | 任务: T171 | 里程碑: M32
