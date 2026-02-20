# T173: 综合练习集 — 后端到前端端到端集成

> **前置阅读**: T166（前端 Hook + SSE）、T170（LangGraph 引擎）、T171（Temporal 持久化工作流）、T172（Prompt Engineering）
> **目标**: 通过 5 个跨层练习，串联后端 AI 管线与前端实时 UI 的完整数据流
> **核心能力**: 理解事件从 LangGraph/Temporal Activity 到前端 React 状态更新的全链路

---

## 为什么需要端到端练习？

T170-T172 分别讲解了后端三大核心：LangGraph 工作流引擎、Temporal 持久化执行、Prompt Engineering 管线。但在真实产品中，这些后端能力必须通过 **SSE 事件流** 传递到前端，由 React Hook 消费并驱动 UI 更新。

本练习集聚焦这条"最后一公里"：

```
LangGraph 节点执行 / Temporal Activity
       │
       │  _push_event() (HTTP POST)
       ▼
  FastAPI EventBus → SSE stream
       │
       │  EventSource (浏览器原生)
       ▼
  useSSEStream (底层抽象)
       │
       │  handlers 分发
       ▼
  useBatchJob / useDesignJob (业务 Hook)
       │
       │  setState
       ▼
  React UI 渲染更新
```

每个练习都要求你在代码中追踪这条链路的某一段，理解数据如何从后端"流"到用户眼前。

---

## 练习 1: Bug Fix 事件端到端追踪

**难度**: ★★☆ | **预计时间**: 30 分钟 | **涉及教材**: T170 + T171 + T166

### 背景

当用户在 Batch Bug Fix 页面提交 3 个 JIRA URL 后，每个 Bug 的修复进度会实时更新在 UI 上。这个实时性来自一条跨越 4 层架构的事件链。

### 任务

追踪一个 `bug_completed` 事件从产生到渲染的完整路径。

### 步骤

**Step 1: 找到事件的源头（后端）**

打开 `backend/workflow/temporal/state_sync.py`，找到 `_sync_incremental_results()` 函数（约 L149）。

问题：
1. 什么时刻触发 `bug_completed` 事件？（提示：看 `result_status == "completed"` 分支）
2. `_push_event(job_id, "bug_completed", {...})` 的 `data` 包含哪些字段？
3. 这个函数同时做了两件事（推 SSE + 写 DB），它们的顺序是什么？为什么这个顺序重要？

**Step 2: 追踪事件的传输（SSE 桥接）**

打开 `backend/workflow/temporal/sse_events.py`（约 L36-48）。

问题：
1. `_push_event` 内部调用了什么？（提示：`push_sse_event`，来自 `workflow/sse.py`）
2. 如果 HTTP POST 失败会怎样？为什么选择"静默失败"而非"抛异常"？
3. T171 提到的"fire-and-forget"模式体现在哪一行代码？

**Step 3: 追踪事件的消费（前端）**

打开 `frontend/app/batch-bugs/hooks/useBatchJob.ts`。

问题：
1. 找到 `bug_completed` 的 SSE handler（约 L119）。它收到事件后做了什么状态更新？
2. `updateBug` 函数（L68-80）用了什么 React 模式来更新数组中的单个元素？（提示：不可变更新）
3. 为什么 handler 引用存储在 `useRef` 而非直接闭包？（提示：看 T166 中关于 handler 稳定性的讲解）

**Step 4: 追踪 UI 渲染**

打开 `frontend/app/batch-bugs/page.tsx`。

问题：
1. `currentJob.bugs` 数组的变更如何触发重新渲染？
2. 每个 Bug 卡片的状态指示器（completed/failed/in_progress）是如何根据 `bug.status` 切换的？

### 交付物

画一张从 `_sync_incremental_results` → `_push_event` → `EventBus` → `SSE stream` → `useSSEStream` → `useBatchJob handler` → `setCurrentJob` → `UI re-render` 的完整事件流图。标注每一步的文件名和行号。

### 思考题

1. 如果 Worker 在推送 `bug_completed` 后、写入 DB 前崩溃了，前端会短暂显示 Bug 已完成。但 Temporal 重新调度 Activity 后，前端页面刷新会怎样？（提示：`useBatchJob` 的 `useEffect` 恢复逻辑，L38-63）
2. T170 讲解的 `MaxIterationsExceeded` 优雅降级中，部分结果如何通过这条链路到达前端？

---

## 练习 2: Design-to-Spec 全链路分析

**难度**: ★★★ | **预计时间**: 45 分钟 | **涉及教材**: T172 + T171 + T166 + T169

### 背景

Design-to-Spec 管线中，SpecAnalyzer 的 Two-Pass 分析（T172）是最慢的阶段。每个组件分析完成后，前端会实时更新组件卡片的状态。同时 Temporal 的 Checkpoint 机制（T171）确保崩溃后不丢进度。

### 任务

追踪一个组件从 Two-Pass 分析完成到前端组件卡片更新的完整路径。

### 步骤

**Step 1: SpecAnalyzer 内部事件（T172 知识）**

打开 `backend/workflow/nodes/spec_analyzer.py`。

问题：
1. `_analyze_single_component` 完成 Two-Pass 后，分析结果（包含 `design_analysis`、`role`、`suggested_name`）如何传回给调用者？
2. `asyncio.gather` 并发分析多个组件时，每个组件的完成事件是如何独立推送的？（提示：看 `_analyze_one` 内部）
3. Semaphore(3) + Stagger delay 如何影响前端看到的组件完成顺序？

**Step 2: Temporal Activity 中的 SSE 推送**

打开 `backend/workflow/temporal/spec_activities.py`。

问题：
1. 找到组件分析完成后推送 SSE 事件的代码。事件类型是什么？
2. Checkpoint 保存（`_save_checkpoint`）和 SSE 推送的先后顺序是什么？这个顺序有什么含义？
3. 语义心跳 `activity.heartbeat(f"phase:analyze_done:{completed}/{total}")` 如何帮助运维人员判断管线卡在哪？

**Step 3: 前端 useDesignJob 消费**

打开 `frontend/app/design-to-code/hooks/useDesignJob.ts`。

问题：
1. 找到 `spec_complete` handler（约 L281）。它做了哪些状态更新？
2. `node_completed` handler 如何更新 `currentNode` 状态？这个状态在 UI 中如何使用？
3. `designSpec` 状态是在哪个事件中被填充的？Spec 数据是通过 SSE 直接推送还是通过 API 拉取？

**Step 4: UI 组件卡片渲染**

打开 `frontend/app/design-to-code/page.tsx`。

问题：
1. 组件分析进度（如 "2/5 完成"）在 UI 的哪个位置显示？
2. 如果分析过程中有一个组件失败（parse_llm_json 全阶段失败 → safe defaults），前端如何区分"成功分析"和"降级分析"？

### 交付物

画两张对比流图：

**正常路径**:
```
Pass 1 (5min) → Pass 2 (2min) → merge → SSE push → UI 组件卡片 ✅
```

**降级路径**:
```
Pass 1 (5min) → Pass 2 (2min) → parse_llm_json 全失败 → retry → 仍失败
    → safe defaults {role:"section"} → 保留 Pass 1 design_analysis → merge
    → SSE push → UI 组件卡片 ⚠️（降级标记？）
```

### 思考题

1. 如果 Worker 在分析第 3 个组件（共 5 个）时崩溃，Temporal 重新调度后，前端会看到什么？（提示：T171 Checkpoint + `useDesignJob` 的恢复逻辑）
2. T172 中提到 Pass 1 的 `design_analysis` 是产品核心资产。如果只有 Pass 2 失败，用户在前端能看到 `design_analysis` 吗？通过什么路径？

---

## 练习 3: 错误传播挑战

**难度**: ★★★☆ | **预计时间**: 45 分钟 | **涉及教材**: T172 + T171 + T166 + T169

### 背景

在生产环境中，LLM 输出不可预测。`parse_llm_json` 的五阶段恢复链（T172）是第一道防线，但如果连这道防线都失败了，错误会如何传播到前端？

### 场景设定

假设 SpecAnalyzer 分析某个复杂组件时：
1. Pass 1 成功，产出了高质量的 `design_analysis` 文本
2. Pass 2 的 LLM 输出了一段无法解析的内容（既不是 JSON 也不是 Markdown）
3. `parse_llm_json` 五阶段全部失败
4. `_retry_with_error_feedback` 重试后，LLM 返回了有效但不完整的 JSON（缺少 `children_updates`）

### 任务

追踪这个错误场景下的完整事件流。

### 步骤

**Step 1: 后端错误处理链（T172 知识）**

1. 打开 `backend/workflow/nodes/llm_utils.py`，走读 `parse_llm_json`（L132-191）。对于"既不是 JSON 也不是 Markdown"的输入，五个阶段分别会发生什么？
2. 打开 `backend/workflow/nodes/spec_analyzer.py`，找到 `_retry_with_error_feedback`（约 L256-319）。重试 prompt 如何构建？错误信息如何被包含？
3. 重试返回的不完整 JSON 能被 `parse_llm_json` 解析成功吗？（提示：`required` 只有 `["role", "description"]`）

**Step 2: Safe Defaults + Merge 路径**

1. 如果重试后的 JSON 缺少 `children_updates`，`merge_analyzer_output`（`spec_merger.py:307-390`）会怎样处理？
2. `_merge_report` 中会记录什么？`children_updates_unmatched` 为空意味着什么？
3. 最终 ComponentSpec 中哪些字段来自 LLM（可能不完整），哪些来自 FrameDecomposer（可靠）？

**Step 3: SSE 事件中的错误信号**

1. 这个组件分析最终是"成功"还是"失败"？（提示：有 `role` 和 `description` 就算成功）
2. 前端 `useDesignJob` 能否区分"完美分析"和"部分降级分析"？
3. 如果你要在前端显示降级警告，需要后端额外推送什么信息？

**Step 4: 设计一个改进方案**

基于你的追踪结果，设计一个**分析质量指示器**：

```typescript
// 在 useDesignJob 中新增
interface ComponentAnalysisQuality {
  componentId: string;
  passOneSuccess: boolean;    // Pass 1 是否成功
  passTwoSuccess: boolean;    // Pass 2 原始解析是否成功
  retryUsed: boolean;         // 是否使用了错误反馈重试
  safeDefaultsUsed: boolean;  // 是否降级到 safe defaults
  childrenUpdatesCount: number; // children_updates 匹配数
}
```

思考：
1. 这些信息从后端的哪里获取？需要在 SSE 事件中新增哪些字段？
2. 前端如何在组件卡片上显示质量等级（如 A/B/C 或颜色标记）？
3. 这个改进需要修改哪些文件？估算修改量。

### 交付物

1. 一张错误传播流图（从 LLM 坏输出 → 最终 UI 显示）
2. 质量指示器的前后端接口设计文档（SSE 事件 schema + React state 定义）

---

## 练习 4: 迷你项目 — Token 消耗实时看板

**难度**: ★★★★ | **预计时间**: 60 分钟 | **涉及教材**: T170 + T171 + T172 + T166 + T169

### 背景

当前 Design-to-Spec 管线的 Token 消耗数据在后端已经收集（T172 提到 `spec_analyzer.py` 的 `total_tokens` 追踪），但前端只在任务完成后显示总量。本项目要求实现 **实时 Token 消耗看板**，让用户在分析过程中就能看到每个组件的 Token 使用情况。

### 目标

```
┌─────────────────────────────────────────┐
│  Token 消耗看板                          │
│                                          │
│  总计: 12,450 input / 3,200 output      │
│  预估费用: $0.18                         │
│                                          │
│  ┌───────────┬──────────┬──────────┐    │
│  │ 组件       │ Input    │ Output   │    │
│  ├───────────┼──────────┼──────────┤    │
│  │ PageHeader │ 2,100    │ 680      │ ✅ │
│  │ HeroSection│ 4,350    │ 1,120    │ ✅ │
│  │ NavBar     │ 3,200    │ 800      │ 🔄 │  ← 分析中
│  │ Footer     │ —        │ —        │ ⏳ │  ← 等待中
│  │ Sidebar    │ —        │ —        │ ⏳ │
│  └───────────┴──────────┴──────────┘    │
└─────────────────────────────────────────┘
```

### 分解步骤

**Step 1: 后端 — 新增 SSE 事件类型（修改 2 个文件）**

在 `spec_activities.py` 中，每个组件 Pass 1 和 Pass 2 完成后，推送一个新的 `component_token_usage` SSE 事件：

```python
# 新增事件 schema
{
    "event_type": "component_token_usage",
    "data": {
        "component_id": "comp-1",
        "component_name": "PageHeader",
        "pass": 1,  # or 2
        "input_tokens": 2100,
        "output_tokens": 680,
        "cumulative_input": 2100,
        "cumulative_output": 680,
    }
}
```

问题：
1. 在 `spec_analyzer.py` 的哪个位置插入 `_push_event` 调用最合适？
2. `cumulative_*` 字段需要在哪里维护累加？
3. 这个新事件需要修改 `sse_events.py` 吗？还是可以直接用现有的 `_push_event`？

**Step 2: 前端 — Hook 层消费（修改 1 个文件）**

在 `useDesignJob.ts` 中新增 `component_token_usage` handler：

```typescript
// 新增 state
const [tokenByComponent, setTokenByComponent] = useState<Map<string, {
  componentName: string;
  inputTokens: number;
  outputTokens: number;
  passes: number; // 已完成的 pass 数
}>>(new Map());

// 新增 handler
component_token_usage: (data) => {
  const compId = data.component_id as string;
  setTokenByComponent(prev => {
    const next = new Map(prev);
    const existing = next.get(compId) || { componentName: "", inputTokens: 0, outputTokens: 0, passes: 0 };
    next.set(compId, {
      componentName: (data.component_name as string) || existing.componentName,
      inputTokens: existing.inputTokens + (data.input_tokens as number || 0),
      outputTokens: existing.outputTokens + (data.output_tokens as number || 0),
      passes: existing.passes + 1,
    });
    return next;
  });
},
```

问题：
1. 为什么用 `Map` 而非普通对象？（提示：有序迭代 + 不受 prototype 污染）
2. 这个 handler 需要加入 `usePipelineConnection` 的 `handlers` 对象吗？
3. `tokenByComponent` 变化时会触发哪些组件重新渲染？如何用 `useMemo` 优化？

**Step 3: 前端 — UI 层渲染（修改/新增 1 个文件）**

设计 `TokenDashboard` 组件：

```typescript
interface TokenDashboardProps {
  tokenByComponent: Map<string, {
    componentName: string;
    inputTokens: number;
    outputTokens: number;
    passes: number;
  }>;
  totalComponents: number;
}
```

需要考虑：
1. 用什么 Tailwind 样式实现上面的表格布局？
2. 数字格式化（`12,450` 而非 `12450`）用 `Intl.NumberFormat` 还是手写？
3. 费用估算公式（Claude Sonnet: $3/M input, $15/M output）放在哪里？前端常量还是后端计算？
4. "分析中 🔄" 和 "等待中 ⏳" 状态如何从 `passes` 字段推断？

**Step 4: 集成测试验证**

描述你会如何验证这个功能：
1. 后端：如何用 `pytest` mock `_push_event` 验证新事件被正确推送？
2. 前端：如何用 React Testing Library 测试 `useDesignJob` 的新 handler？
3. E2E：Playwright 如何验证 Token 看板在分析过程中实时更新？

### 交付物

1. 后端修改清单（文件 + 行号 + 改动描述）
2. 前端修改清单（文件 + 改动描述）
3. `TokenDashboard` 组件的完整 TypeScript 代码
4. 3 个测试用例描述

### 思考题

1. 如果用户在分析过程中刷新页面，Token 看板数据会丢失。如何通过 DB 持久化 + 恢复逻辑解决？参考 `useBatchJob` 的 recovery pattern。
2. 多个组件并发分析时（Semaphore=3），SSE 事件可能乱序到达。`tokenByComponent` 的累加逻辑是否受影响？
3. T171 提到 Temporal 的语义心跳已经携带进度信息（`f"phase:analyze_done:{completed}/{total}"`），能否复用这个机制代替新增 SSE 事件？为什么？

---

## 练习 5: CCCC vs work-flow 架构对比分析

**难度**: ★★☆ | **预计时间**: 30 分钟 | **涉及教材**: T164 + T170 + T171 + T166

### 背景

你每天都在使用 CCCC 多 Agent 系统协作开发 work-flow 项目。这两个系统有惊人的架构相似性——理解一个能帮你更快理解另一个。

### 任务

从 4 个维度对比 CCCC 和 work-flow 的架构设计，理解共性设计原则。

### Step 1: 进程隔离

**CCCC 架构**：
```
ccccd (Daemon) — 进程管理 + 消息路由
  └─ Agent PTY (独立进程) — 执行任务 (claude, codex 等)
```

**work-flow 架构**：
```
FastAPI (:8000) — HTTP 入口 + SSE 推送
  └─ Temporal Worker (独立进程) — 执行 Activity (Claude CLI 调用)
```

问题：
1. 为什么两个系统都把"重活"放在独立进程里？（提示：T171 1.1 节的事件循环饥饿问题）
2. CCCC 的 Agent PTY 崩溃后如何恢复？work-flow 的 Temporal Worker 崩溃后如何恢复？两者的恢复保证有什么差异？
3. CCCC 的 Daemon 通过 Unix Socket 与 Web 通信，work-flow 的 Worker 通过 HTTP POST 推 SSE 事件。为什么选择不同的通信方式？

### Step 2: 事件驱动

**CCCC 的事件系统**：
```
Agent → MCP 工具调用 → Daemon → Ledger 事件日志
                                → 目标 Agent inbox
                                → Web UI 更新
```

**work-flow 的事件系统**：
```
Worker → _push_event() HTTP POST → FastAPI EventBus
                                  → SSE stream → 前端
                                  → DB 持久化
```

问题：
1. CCCC 的 `cccc_message_send` 和 work-flow 的 `_push_event` 分别是同步还是异步？为什么？
2. 两个系统都实现了"发送失败不中断主流程"。找到各自的实现代码。（提示：CCCC 的 MCP 工具有内置重试；work-flow 的 `_push_event` 在 `sse_events.py:36-48`）
3. CCCC 的 Ledger 和 work-flow 的 EventBus 有一个关键区别：持久化程度。这对故障恢复有什么影响？

### Step 3: 可观测性

| 维度 | CCCC | work-flow |
|------|------|-----------|
| 实时状态 | `cccc_presence_get` | SSE `node_update` 事件 |
| 日志追踪 | `cccc_terminal_tail` | Temporal Web UI |
| 进度查询 | `cccc_context_get` (tasks) | DB 查询 (`getBatchJobStatus`) |
| 健康检查 | `silence_check` + `keepalive` | Temporal `heartbeat_timeout` |

问题：
1. 你正在使用 `cccc_terminal_tail` 查看 peer 的终端输出。work-flow 中有等价功能吗？如果没有，用什么替代？
2. CCCC 的 `silence_check` 检测 Agent 是否"沉默太久"。这和 Temporal 的 `heartbeat_timeout` 解决的是同一个问题吗？
3. work-flow 的前端通过 `useSSEStream` 的 `stale` 标志检测连接是否断开（`heartbeatTimeoutMs`）。CCCC 有类似机制吗？

### Step 4: 持久化策略

| 维度 | CCCC | work-flow |
|------|------|-----------|
| 事件存储 | Ledger（JSON 事件日志） | SQLite (BatchJob/DesignJob) |
| 状态恢复 | Context（vision/sketch/tasks） | DB + Temporal 历史 |
| 工作流状态 | group_state (active/idle/paused) | job_status (running/completed/failed) |
| 崩溃恢复 | Agent 重启 + Context 读取 | Temporal 重新调度 + Checkpoint |

问题：
1. CCCC 的 Context 和 work-flow 的 DB 都是"真实状态源"（source of truth）。它们的一致性保证有什么不同？
2. 如果你是架构师，要为 CCCC 添加"Temporal 级别的持久化执行保证"，需要改什么？代价是什么？
3. work-flow 的 `_sync_final_results` 有 4 次重试 + 指数退避（T171 3.3 节）。CCCC 的 Ledger 写入有类似保护吗？

### 交付物

一张 2×4 对比表格（2 个系统 × 4 个维度），每个格子包含：
- 核心机制名称
- 源码位置（CCCC 用 MCP 工具名，work-flow 用文件名:行号）
- 设计 trade-off（选择了什么，放弃了什么）

### 思考题

1. 如果要用 Temporal 替换 CCCC 的 Agent 管理（让 Daemon 通过 Temporal 调度 Agent），会获得什么？失去什么？
2. 两个系统的"编排 vs 执行分离"原则一致，但实现方式不同。哪种方式更适合什么场景？

---

## 跨练习知识串联图

```
T170 LangGraph                T171 Temporal               T172 Prompt
    │                              │                          │
    │ node_func 闭包               │ Activity 执行             │ Two-Pass
    │ 状态合并                     │ 心跳上报                  │ parse_llm_json
    │ MaxIterationsExceeded        │ Checkpoint 恢复           │ safe defaults
    │                              │ SSE 事件推送              │
    └──────────────┬───────────────┘                          │
                   │                                          │
                   ▼                                          │
           _push_event (HTTP POST)  ←─────────────────────────┘
                   │
                   ▼
        T166 前端 Hook + SSE
                   │
    ┌──────────────┼──────────────┐
    ▼              ▼              ▼
useSSEStream  useBatchJob  useDesignJob
    │              │              │
    ▼              ▼              ▼
T169 前端工程
    │
    ├─ Next.js App Router (路由 + 布局)
    ├─ React 组件 (状态 → UI)
    └─ Tailwind CSS (样式)
```

| 练习 | 主线 | 串联的教材 |
|------|------|----------|
| 1. Bug Fix 追踪 | LangGraph 循环 → SSE → Bug 卡片 | T170 + T171 + T166 |
| 2. Spec 全链路 | Two-Pass → Checkpoint → 组件卡片 | T172 + T171 + T166 |
| 3. 错误传播 | JSON 解析失败 → safe defaults → UI | T172 + T171 + T166 + T169 |
| 4. Token 看板 | 新增后端事件 → 新增 Hook → 新增 UI | T170 + T171 + T172 + T166 + T169 |
| 5. CCCC 对比 | 进程隔离 + 事件驱动 + 可观测性 + 持久化 | T164 + T170 + T171 + T166 |

---

## 参考答案提示

> 以下不是完整答案，而是关键方向提示。建议先自己动手再对照。

### 练习 1 关键路径

```
state_sync.py:178  _push_event(job_id, "bug_completed", {...})
    → sse_events.py:36  _push_event → push_sse_event
    → sse.py             HTTP POST → FastAPI /api/internal/events/{job_id}
    → event_bus.py        EventBus.publish(job_id, event)
    → SSE stream          EventSource 收到 event
    → useSSEStream.ts     dispatch to handler
    → useBatchJob.ts:119  bug_completed handler → updateBug → setCurrentJob
    → page.tsx            React re-render Bug 卡片
```

### 练习 2 关键区分

- `spec_complete` 事件触发 `designSpec` 的拉取（通过 API `getDesignJobSpec`），不是直接通过 SSE 推送 spec 数据
- 原因：完整 DesignSpec 可能很大（100KB+），不适合放在 SSE 事件 payload 中

### 练习 3 关键发现

- 当前前端**无法区分**"完美分析"和"降级分析"— 后端没有推送分析质量元数据
- 这是一个真实的产品改进点，练习 4 的 Token 看板是类似模式的具体实现

### 练习 4 的 `_push_event` 插入点

```python
# spec_analyzer.py: _analyze_single_component 方法中
# Pass 1 完成后（约 L380）
if pass1_result["token_usage"]:
    await _push_event(job_id, "component_token_usage", {
        "component_id": comp_id,
        "component_name": comp_name,
        "pass": 1,
        "input_tokens": pass1_result["token_usage"]["input_tokens"],
        "output_tokens": pass1_result["token_usage"]["output_tokens"],
    })

# Pass 2 完成后（约 L412）同理
```

---

> 作者: code-simplifier | 任务: T173-S2 | 里程碑: M32
