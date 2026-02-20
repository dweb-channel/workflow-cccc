# T164: 项目架构全景讲解

> **目标**：30 分钟内建立全局心智模型
> **作者**：domain-expert（领域专家）
> **适用对象**：目标成为高级 AI 应用开发工程师的开发者

---

## 目录

1. [一句话概括](#一句话概括)
2. [技术栈全景](#技术栈全景)
3. [核心目录索引](#核心目录索引)
4. [管线 1：批量 Bug 修复](#管线-1批量-bug-修复)
5. [管线 2：Design-to-Spec](#管线-2design-to-spec)
6. [关键设计决策复盘](#关键设计决策复盘)
7. [进阶阅读路径](#进阶阅读路径)

---

## 一句话概括

**Work-Flow** 是一个开源开发者工作流编排平台，通过 LangGraph + Temporal 编排 AI Agent，提供两条核心管线：**批量 Bug 修复**（Jira → Claude 修复 → 验证 → Git PR）和 **Design-to-Spec**（Figma → 结构提取 → Claude 视觉分析 → 设计规格 JSON）。

---

## 技术栈全景

```
┌─────────────────────────────────────────────────────────┐
│                    用户浏览器                              │
│         Next.js 14 + React 18 + Tailwind CSS             │
│         React Flow (DAG 编辑器) + SSE (实时事件流)         │
└────────────────────────┬────────────────────────────────┘
                         │ HTTP REST + SSE
┌────────────────────────▼────────────────────────────────┐
│                   FastAPI 后端                            │
│   Routes → Repositories → SQLAlchemy (async) → SQLite    │
│   EventBus → SSE 推送                                    │
│   TemporalAdapter → 启动异步工作流                        │
└────────────────────────┬────────────────────────────────┘
                         │ Temporal RPC
┌────────────────────────▼────────────────────────────────┐
│               Temporal Worker（独立进程）                  │
│   BatchBugFixWorkflow → execute_batch_bugfix_activity     │
│   SpecPipelineWorkflow → execute_spec_pipeline_activity   │
│                         │                                │
│         ┌───────────────▼──────────────────┐             │
│         │      LangGraph 执行引擎           │             │
│         │  graph_builder.py → executor.py   │             │
│         │  StateGraph + astream()           │             │
│         └───────────────┬──────────────────┘             │
│                         │                                │
│         ┌───────────────▼──────────────────┐             │
│         │     工作流节点 (Nodes)             │             │
│         │  agents.py → Claude CLI 调用      │             │
│         │  frame_decomposer.py → 结构提取   │             │
│         │  spec_analyzer.py → LLM 视觉分析  │             │
│         └──────────────────────────────────┘             │
└─────────────────────────────────────────────────────────┘
         │                              │
    Claude CLI                    Figma API / Jira API
  (AI 代码修复/分析)            (设计稿获取 / Bug 信息)
```

### 分层职责

| 层级 | 技术 | 职责 | 关键文件 |
|------|------|------|----------|
| **前端** | Next.js 14 + React 18 | 用户交互、实时状态展示 | `frontend/app/` |
| **API 层** | FastAPI | REST 端点、SSE 推送、DB 操作 | `backend/app/routes/` |
| **数据层** | SQLAlchemy async + SQLite | ORM 模型、Repository 模式 | `backend/app/models/`, `repositories/` |
| **调度层** | Temporal | 持久化工作流执行、重试、心跳 | `backend/workflow/temporal/` |
| **编排层** | LangGraph | 有状态 DAG 执行、条件路由、循环 | `backend/workflow/engine/` |
| **节点层** | Python + Claude CLI | 具体业务逻辑（修 Bug、分析设计） | `backend/workflow/nodes/` |
| **集成层** | httpx | Figma API、Jira API、Claude CLI | `backend/workflow/integrations/` |

---

## 核心目录索引

### 后端 (`backend/`)

```
backend/
├── app/                           # FastAPI 应用层（HTTP 入口）
│   ├── main.py                    # ★ 入口：FastAPI app 创建、路由注册、CORS
│   ├── database.py                # ★ 数据库：async SQLAlchemy 引擎 + session
│   ├── event_bus.py               # ★ SSE 基础设施：事件缓冲 + 队列分发
│   ├── temporal_adapter.py        # Temporal 客户端单例
│   ├── models/
│   │   ├── db.py                  # ★ ORM 模型：BatchJob, DesignJob, Workspace
│   │   └── schemas.py             # Pydantic 请求/响应 schema
│   ├── repositories/
│   │   ├── batch_job.py           # BatchJob CRUD
│   │   └── design_job.py          # DesignJob CRUD
│   └── routes/
│       ├── batch.py               # ★ 批量 Bug 修复 API 端点
│       ├── design.py              # ★ Design-to-Spec API 端点
│       └── workspace.py           # Workspace 管理
│
├── workflow/                      # 工作流编排层（核心业务逻辑）
│   ├── engine/
│   │   ├── graph_builder.py       # ★ LangGraph DAG 构建器
│   │   ├── executor.py            # ★ LangGraph 执行器（astream 驱动）
│   │   └── safe_eval.py           # 安全表达式求值（条件节点）
│   ├── nodes/
│   │   ├── agents.py              # ★ LLM Agent 节点（Claude CLI 调用）
│   │   ├── frame_decomposer.py    # ★ Figma 帧分解器（结构提取 70%）
│   │   ├── spec_analyzer.py       # ★ Spec 分析器（LLM 视觉 30%）
│   │   ├── spec_assembler.py      # Spec 组装器（验证+输出）
│   │   └── spec_merger.py         # LLM 输出合并到 Spec
│   ├── temporal/
│   │   ├── batch_workflow.py      # Temporal 批量修复工作流
│   │   ├── batch_activities.py    # ★ 批量修复核心活动
│   │   ├── spec_workflow.py       # Temporal 设计管线工作流
│   │   ├── spec_activities.py     # ★ 设计管线核心活动
│   │   ├── state_sync.py          # ★ 状态同步：工作流 → DB
│   │   └── worker.py              # Worker 启动入口
│   ├── integrations/
│   │   └── figma_client.py        # ★ Figma API 客户端
│   ├── spec/
│   │   ├── spec_analyzer_prompt.py # ★ Claude 视觉分析 Prompt
│   │   └── spec_merger.py         # Spec 合并逻辑
│   └── claude_cli_wrapper.py      # ★ Claude CLI 封装
```

### 前端 (`frontend/`)

```
frontend/
├── app/
│   ├── layout.tsx                 # ★ 根布局：Sidebar + ThemeProvider
│   ├── page.tsx                   # 首页：工作流画布编辑器
│   ├── globals.css                # ★ CSS 变量（深色/浅色主题）
│   ├── batch-bugs/
│   │   ├── page.tsx               # ★ 批量 Bug 修复主页
│   │   ├── hooks/useBatchJob.ts   # ★ 批量任务 Hook（SSE + 状态）
│   │   └── components/            # ActivityFeed, BugInput, ConfigOptions...
│   └── design-to-code/
│       ├── page.tsx               # ★ Design-to-Code 主页
│       ├── hooks/useDesignJob.ts  # ★ 设计任务 Hook（SSE + 状态恢复）
│       └── spec-browser/          # 交互式 Spec 浏览器
├── lib/
│   ├── api.ts                     # ★ API 客户端（所有后端调用）
│   └── useSSEStream.ts            # ★ SSE 流消费 Hook
└── components/
    ├── sidebar/Sidebar.tsx        # 导航侧栏
    └── ui/                        # shadcn/ui 组件库
```

> **★ = 建议优先阅读的文件**

---

## 管线 1：批量 Bug 修复

### 端到端数据流

```
用户输入 Jira URLs + 工作目录
        │
        ▼
POST /api/v2/batch/bug-fix
        │ 创建 BatchJobModel (status=started)
        │ 创建 BugResultModel × N (status=pending)
        │ 启动 Temporal Workflow
        ▼
┌─ Temporal Worker ──────────────────────────────────────┐
│                                                        │
│  execute_batch_bugfix_activity()                       │
│    │                                                   │
│    ├─ 1. 预检 (preflight_check)                        │
│    │     验证 Claude CLI、git、cwd 是否可用             │
│    │                                                   │
│    ├─ 2. 预扫描 (prescan_closed_bugs)                  │
│    │     检查 Jira 状态，已关闭的 Bug 直接跳过           │
│    │                                                   │
│    └─ 3. LangGraph 执行                                │
│         │                                              │
│    ┌────▼────────────────────────────────────────────┐ │
│    │           LangGraph StateGraph                  │ │
│    │                                                 │ │
│    │  input_node → get_current_bug                   │ │
│    │       │                                         │ │
│    │       ▼                                         │ │
│    │  fix_bug_peer (Claude CLI 修复代码)              │ │
│    │       │                                         │ │
│    │       ▼                                         │ │
│    │  verify_fix (Claude CLI 验证修复)                │ │
│    │       │                                         │ │
│    │       ▼                                         │ │
│    │  check_verify_result ──┐                        │ │
│    │       │ VERIFIED       │ FAILED                 │ │
│    │       ▼                ▼                        │ │
│    │  update_success   check_retry                   │ │
│    │       │               │ 可重试    │ 不可重试    │ │
│    │       │               ▼           ▼            │ │
│    │       │         increment_retry  update_failure │ │
│    │       │               │                │       │ │
│    │       ▼               │ (回到 fix)     │       │ │
│    │  check_more_bugs ◄────┘────────────────┘       │ │
│    │       │ 还有          │ 没有了                  │ │
│    │       │ (回到 get)    ▼                        │ │
│    │       └──────►  output_node                    │ │
│    └─────────────────────────────────────────────────┘ │
│                                                        │
│  每个节点完成后：                                        │
│    → 更新 DB (BugResultModel.steps)                    │
│    → 推送 SSE 事件 (bug_step_completed)                │
│    → Temporal 心跳 (防超时)                             │
│                                                        │
│  最终同步：                                             │
│    → _sync_final_results() 更新 DB 终态                │
│    → 推送 job_done 事件                                │
└────────────────────────────────────────────────────────┘
        │
        ▼
前端通过 SSE 实时展示：
  bug_started → ai_thinking → bug_step_completed → job_done
```

### 关键状态流转

```
BatchJob:  started → running → completed / failed / cancelled
Bug:       pending → in_progress → completed / failed / skipped
Step:      getting → fixing → verifying → completed / failed
```

### 重试机制

- **单 Bug 内重试**：`check_retry` 节点检查 `retry_count < max_retries`，回到 `fix_bug_peer` 重新尝试
- **上下文积累**：每次重试带上前次的 `verify_feedback`，prompt 明确要求"换一种思路"
- **单 Bug 手动重试**：`POST /api/v2/batch/bug-fix/{job_id}/retry/{bug_index}`，启动新 Temporal Workflow

---

## 管线 2：Design-to-Spec

### 端到端数据流

```
用户输入 Figma URL
        │
        ▼
POST /api/v2/design/run-spec
        │ 解析 URL → (file_key, node_id)
        │ 创建 DesignJobModel
        │ 启动 Temporal Workflow
        ▼
┌─ Temporal Worker ──────────────────────────────────────┐
│                                                        │
│  execute_spec_pipeline_activity()                      │
│                                                        │
│  Phase 1: Figma 数据获取                                │
│    ├─ FigmaClient.get_file_nodes() → 节点树            │
│    ├─ FigmaClient.download_screenshots() → PNG × N     │
│    └─ FigmaClient.get_design_tokens() → 颜色/字体/间距  │
│                                                        │
│  Phase 2: FrameDecomposer（纯 Python，无 LLM）          │
│    ├─ figma_node_to_component_spec() 递归转换           │
│    │   Figma 属性 → ComponentSpec（填充 70% 字段）       │
│    │   bounds, layout, style, typography, children      │
│    ├─ 留空语义字段（30%）：role, description, render_hint │
│    └─ 输出：PartialComponentSpec[]                      │
│                                                        │
│  Phase 3: SpecAnalyzer（Claude 视觉分析）                │
│    ├─ Pass 1: 截图 + 结构数据 → Claude Vision            │
│    │   输出：design_analysis（自由文本 markdown）         │
│    ├─ Pass 2: Pass1 结果 → Claude（无截图）              │
│    │   输出：结构化 JSON（role, suggested_name, etc.）    │
│    ├─ 并发控制：semaphore=3, stagger=2.0s               │
│    ├─ 断点恢复：.spec_checkpoints/ 目录                  │
│    └─ 合并：spec_merger 将 LLM 输出合并回组件树          │
│                                                        │
│  Phase 4: SpecAssembler（验证+输出）                     │
│    ├─ z_index 排序 + 名称去重                           │
│    ├─ 质量验证（role 一致性、bounds 溢出、命名质量）      │
│    └─ 写入 design_spec.json                             │
│                                                        │
└────────────────────────────────────────────────────────┘
        │
        ▼
输出文件：
  spec_{job_id}/
  ├── design_spec.json          # 核心输出（4KB-100KB）
  ├── screenshots/*.png         # 组件截图（2x 分辨率）
  └── .spec_checkpoints/*.json  # 断点恢复缓存
```

### SpecAnalyzer 双 Pass 设计 —— 为什么？

```
为什么不一步到位？

Pass 1（自由文本 + 截图）：
  ✅ LLM 可以"看图说话"，不受 JSON 格式约束
  ✅ 输出丰富的设计分析（用于 design_analysis 字段）
  ❌ 非结构化，无法直接用于代码

Pass 2（结构化 JSON，无截图）：
  ✅ 基于 Pass 1 的分析提取结构化数据
  ✅ JSON <50 行，parse 成功率高
  ✅ 不需要截图，省 token
  ❌ 如果 Pass 1 分析不准，Pass 2 也不准

这是一个 "先发散再收敛" 的策略：
  LLM 在 Pass 1 自由思考 → Pass 2 精准提取
  类似于 Chain-of-Thought 的思路
```

---

## 关键设计决策复盘

### 决策 1：为什么从 asyncio 迁移到 Temporal Worker

**问题**：页面冻结 Bug

```
最初的架构：
  FastAPI (单进程)
    └─ asyncio.create_task(workflow)
         └─ stream_claude_events() 紧密循环

问题：
  stream_claude_events() 使用 readline() 读取 Claude CLI 输出
  当 StreamReader buffer 有数据时，readline() 立即返回，不 yield 给事件循环
  → 整个事件循环被饿死
  → FastAPI 无法处理其他请求
  → 前端页面冻结

临时修复：
  在循环中加 await asyncio.sleep(0) 强制让出控制
  → 有效但治标不治本

最终方案（M10）：
  将批量工作流迁移到 Temporal Worker（独立进程）
  → FastAPI 进程只处理 HTTP 请求
  → Worker 进程跑 Claude CLI，自己阻塞无所谓
  → 通过 HTTP POST 回传 SSE 事件给 FastAPI
  → 彻底解决事件循环饥饿问题
```

**教训**：
- CPU 密集型 / IO 阻塞型任务不要放在 asyncio 事件循环里
- "独立进程" 是最可靠的隔离方式
- Temporal 附赠了持久化、重试、心跳等生产级能力

**相关文件**：
- `backend/workflow/temporal/worker.py` — Worker 独立进程
- `backend/workflow/temporal/batch_activities.py` — Activity 实现
- `backend/app/event_bus.py` — SSE 事件从 Worker → FastAPI

---

### 决策 2：State Merge 从白名单改为黑名单

**问题**：Design-to-Spec 管线的 LangGraph 状态字段被静默丢弃

```
最初的设计（白名单）：
  _MERGE_ALLOW_KEYS = {"bugs", "current_index", "results", "context", ...}

  问题：
  - 这是 Batch Bug Fix 专用的字段列表
  - Design-to-Spec 管线有自己的字段（components, page, design_tokens）
  - 这些字段不在白名单里 → 合并时被静默丢弃
  - 下游节点拿到空数据 → 管线失败
  - 排查了很久才发现，因为"静默丢弃"没有报错

修复（黑名单）：
  _MERGE_SKIP_KEYS = {"updated_fields", "error", "has_more", "node_id", "node_type"}

  只跳过已知的"不应合并"的元数据字段
  其他所有字段都通过 → 引擎层不再耦合业务字段名
```

**教训**：
- 引擎层（通用组件）绝不能包含业务字段名
- 白名单 = 封闭世界假设，新功能必须修改引擎 → 违反开闭原则
- 黑名单 = 开放世界假设，只排除已知问题 → 更安全
- "静默丢弃"是最难调试的 Bug 类型，永远优先于"静默忽略"

**相关文件**：
- `backend/workflow/engine/graph_builder.py:91` — `_DEFAULT_MERGE_SKIP_KEYS` 定义

---

### 决策 3：SSE 事件流 + 状态恢复架构

**问题**：已完成的 Job 页面显示"No design spec available."

```
最初的设计（纯 SSE）：
  前端 designSpec 状态只通过 SSE 事件填充
  Job 完成后不会再有 SSE 事件
  → 用户刷新页面 → designSpec = null → "No design spec available."

而实际上：
  design_spec.json 在磁盘上完好存在
  GET /api/v2/design/{job_id}/spec 可以返回数据
  但前端从来没调用这个 API

根因：
  只依赖实时流（SSE）获取数据
  没有考虑"回到已完成任务"的恢复路径

修复：
  useDesignJob hook 中加 recovery useEffect：
  当 designSpec === null && job.design_file 存在时
  → 调用 getDesignJobSpec(jobId) 从后端读取磁盘文件
```

**教训**：
- 实时流（SSE/WebSocket）只能覆盖"在线时"的数据
- 必须有独立的"状态恢复"路径（REST API 读取持久化数据）
- 设计 SSE 架构时，永远要问：**用户刷新页面后会怎样？**
- 事件缓冲（EventBus 最多缓存 200 条、10 分钟）只是临时方案，不替代持久化恢复

**相关文件**：
- `frontend/app/design-to-code/hooks/useDesignJob.ts:55-65` — recovery: `getDesignJobSpec()` 加载磁盘 spec
- `backend/app/routes/design.py` — spec 读取端点
- `backend/app/event_bus.py` — 事件缓冲机制

---

### 决策 4：LangGraph 内外状态脱节

**问题**：循环中外部状态与 LangGraph 内部状态不同步

```
executor.py 原始代码：
  async for event in compiled_graph.astream(state, config):
      for node_id, node_output in event.items():
          state[node_id] = node_output    # ← 只存了节点名 key，丢了顶层状态！

问题：
  LangGraph astream() 维护独立的内部状态
  外部 state 变量是独立的 copy
  在循环中，内部状态正确积累，但外部 state 可能落后
  例：component_registry 在内部正确积累，但外部 copy 始终为空

修复（当前代码 executor.py:151）：
  if isinstance(node_output, dict):
      state.update(node_output)     # ← 合并全部顶层 key
  else:
      state[node_id] = node_output  # ← fallback
```

**教训**：
- 使用框架的 streaming API 时，必须理解框架的内部状态管理机制
- "外部变量跟踪内部状态"是一个常见的陷阱
- 最终结果应该从框架的正式输出读取，而不是从外部跟踪变量

**相关文件**：
- `backend/workflow/engine/executor.py:147-154` — 状态合并逻辑（已修复版本）

### 决策 5：FrameDecomposer 70/30 分拆策略

**问题**：Design-to-Spec 全部依赖 LLM 视觉分析，速度慢、成本高、不稳定

```
朴素方案：
  截图 → Claude Vision → 完整 ComponentSpec JSON

问题：
  - 每个组件需要分析截图 + 输出大 JSON → token 成本高
  - 布局数据（position, width, height, padding, gap）LLM 经常出错
  - 颜色值 LLM 经常不精确（#1a1a1a vs #1b1b1b）
  - Figma API 已经提供了精确的结构数据，让 LLM 重复猜测是浪费

最终方案（70/30 分拆）：

  Phase 1 — FrameDecomposer（纯 Python，无 LLM）：
    figma_node_to_component_spec() 递归遍历 Figma 节点树
    精确提取 70% 字段：
      ✅ bounds (x, y, width, height)
      ✅ layout (auto-layout direction, gap, padding)
      ✅ style (fill, stroke, cornerRadius, opacity)
      ✅ typography (fontFamily, fontSize, fontWeight, lineHeight)
      ✅ children 递归结构

  Phase 2 — SpecAnalyzer（Claude Vision）：
    只负责 30% 语义字段：
      ✅ role（button / card / nav / hero …）
      ✅ description（组件用途的自然语言描述）
      ✅ render_hint（实现建议）
      ✅ suggested_name（语义化命名）
```

**Trade-off**：

| | 全 LLM | 70/30 分拆 |
|--|--------|-----------|
| 准确度 | 布局/颜色不精确 | 结构精确 + 语义准确 |
| 速度 | 慢（每组件需截图分析） | 快（Phase 1 毫秒级） |
| 成本 | 高（大 JSON 输出） | 低（LLM 只输出语义字段） |
| 可调试性 | 黑盒 | Phase 1 输出可独立检查 |
| 复杂度 | 简单 | 需要维护 Figma 属性映射 |

**教训**：
- 能用确定性代码做的事，不要交给 LLM
- LLM 最擅长语义理解和创造性判断，最不擅长精确数值
- "分拆"策略让两种能力各司其职

**相关文件**：
- `backend/workflow/nodes/frame_decomposer.py:75` — `FrameDecomposerNode`
- `backend/workflow/nodes/figma_spec_builder.py` — `figma_node_to_component_spec()` 递归转换
- `backend/workflow/nodes/spec_analyzer.py` — LLM 视觉分析（30%）

---

## 进阶阅读路径

### 路径 A：理解 LangGraph 编排（AI 工程核心）

```
建议阅读顺序：
1. backend/workflow/engine/graph_builder.py     ← DAG 怎么构建
2. backend/workflow/engine/executor.py          ← astream() 怎么执行
3. backend/workflow/nodes/agents.py             ← Claude CLI 怎么调用
4. backend/workflow/temporal/batch_activities.py ← 完整的 Activity 实现
```

### 路径 B：理解前后端实时通信（全栈能力）

```
建议阅读顺序：
1. backend/app/event_bus.py                     ← SSE 基础设施
2. backend/workflow/temporal/state_sync.py      ← Worker → DB → SSE
3. frontend/lib/useSSEStream.ts                 ← 前端 SSE 消费
4. frontend/app/batch-bugs/hooks/useBatchJob.ts ← 完整的状态管理
```

### 路径 C：理解 Design-to-Spec 管线（AI 视觉应用）

```
建议阅读顺序：
1. backend/workflow/integrations/figma_client.py    ← Figma API 调用
2. backend/workflow/nodes/frame_decomposer.py       ← 结构提取 (70%)
3. backend/workflow/spec/spec_analyzer_prompt.py    ← Prompt 设计
4. backend/workflow/nodes/spec_analyzer.py          ← LLM 视觉分析 (30%)
5. backend/workflow/spec/spec_merger.py             ← 合并策略
```

---

## 附录：SSE 事件类型速查

### 批量 Bug 修复

| 事件 | 触发时机 | 关键数据 |
|------|----------|----------|
| `job_state` | SSE 连接建立 | 完整 Job 状态 |
| `preflight_passed` | 预检通过 | warnings |
| `bug_started` | 开始处理某个 Bug | bug_index, url |
| `bug_step_started` | 步骤开始 | step, label |
| `ai_thinking` | Claude 执行工具 | type (read/edit/bash), description |
| `bug_step_completed` | 步骤完成 | step, status, duration_ms |
| `bug_completed` | Bug 修复成功 | bug_index, url |
| `bug_failed` | Bug 修复失败 | bug_index, error |
| `job_done` | 任务结束 | status, completed, failed |

### Design-to-Spec

| 事件 | 触发时机 | 关键数据 |
|------|----------|----------|
| `figma_fetch_start` | 开始获取 Figma 数据 | - |
| `figma_fetch_complete` | 获取完成 | components_count |
| `frame_decomposed` | 结构提取完成 | components, page |
| `spec_analyzed` | 单个组件分析完成 | component_name, role, tokens_used |
| `job_done` | 管线结束 | status, components_total |

---

> **下一步**：结合 superpowers-peer 的 T165（Claude API 教程）和 code-simplifier 的 T166（前端 Hook 走读），选择上面的进阶路径深入学习。
