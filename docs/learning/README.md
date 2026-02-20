# 高级 AI 应用开发工程师 — 学习路线图

> 基于 work-flow 项目实战，6 周从入门到独立开发多 Agent 系统。

---

## 学习方式

每个主题采用 **讲解 → 走读 → 动手 → 复盘** 四步循环：
1. 先读架构讲解（WHY）
2. 再看代码走读（HOW）
3. 跟着实操指南动手
4. 复盘踩坑和 trade-off

---

## Phase 1: 基础 + 项目全景（Week 1）

**目标**：30 分钟建立全局心智模型，跑通两条 Pipeline，开始接触 Claude API

### 阅读顺序

| 序号 | 文档 | 内容 | 预计时间 |
|------|------|------|----------|
| 1 | [项目架构全景](./t164-architecture-overview.md) | 数据流图 + 目录索引 + 3 个关键设计决策 | 30 min |
| 2 | [Pipeline 实操指南](./t167-pipeline-guide.md) | Batch Bug Fix + Design-to-Spec 实操 | 45 min |
| 3 | [前端 Hook + SSE 走读](./t166-frontend-hooks-sse.md) | SSE 三层架构 + 7 个设计模式 + 组件拆分 | 60 min |
| 4 | [Claude API + Prompt 教学](./t165-claude-api-prompt.md) | API 基础 + Tool Use + 踩坑集锦 | 60 min |
| 5 | [前端工程实战](./t169-frontend-engineering.md) | Next.js App Router + React 组件模式 + Tailwind 深色模式 | 60 min |

### 核心技术点

- **Python asyncio** — `async/await`、事件循环、`StreamReader`
- **FastAPI** — 路由、依赖注入、Pydantic、SSE
- **React Hooks** — `useState`/`useEffect`/`useCallback`/`useRef`、自定义 Hook
- **TypeScript** — 泛型、类型守卫、discriminated union
- **SSE (Server-Sent Events)** — 实时推送、断线重连、状态恢复
- **Next.js App Router** — layout/page/error 约定、Server vs Client Component
- **Tailwind CSS** — CSS 变量主题、shadcn/ui 组件库、class-variance-authority

### 关键文件入口

```
backend/
  app/routes/design.py          ← Design-to-Code API 路由
  app/routes/batch.py           ← Batch Bug Fix API 路由
  workflow/engine/executor.py   ← LangGraph 执行引擎
  workflow/claude_cli_wrapper.py ← Claude CLI 调用封装

frontend/
  app/design-to-code/           ← Design-to-Code 页面
    hooks/useDesignJob.ts        ← 核心 Hook
  app/batch-bugs/               ← Batch Bug Fix 页面
    hooks/useBatchJob.ts         ← 核心 Hook
  lib/useSSEStream.ts           ← SSE 底层抽象
  lib/usePipelineConnection.ts  ← Pipeline 连接管理
```

---

## Phase 2: AI 工程核心（Week 2-3）

**目标**：掌握 LangGraph 工作流编排 + Prompt Engineering 进阶

### 阅读顺序

| 序号 | 文档 | 内容 | 预计时间 |
|------|------|------|----------|
| 1 | [LangGraph 工作流引擎深入教程](./t170-langgraph-engine.md) | StateGraph 构建 + 条件路由 + safe_eval 沙箱 + 循环控制 + 节点注册表 | 90 min |
| 2 | [Prompt Engineering 进阶](./t172-prompt-engineering.md) | Two-Pass 管线 + CodeGen Prompt + parse_llm_json 恢复链 + spec_merger | 75 min |

### 核心技术点

- **LangGraph StateGraph** — 节点、边、条件路由、循环控制
- **状态管理深水区** — 内部/外部 state 同步（真实踩坑案例）
- **safe_eval AST 沙箱** — 白名单安全模型、条件表达式求值
- **Prompt Engineering** — Two-Pass 管线、结构化输出约束、token 优化
- **JSON 恢复链** — parse_llm_json 五阶段渐进恢复
- **Claude stream-json** — `result` 只含最后 assistant text 的陷阱

### 关键文件入口

```
backend/
  workflow/engine/graph_builder.py  ← StateGraph 构建
  workflow/engine/executor.py       ← 工作流执行 + astream
  workflow/engine/safe_eval.py      ← AST 沙箱表达式求值
  workflow/nodes/registry.py        ← 策略模式节点注册表
  workflow/nodes/spec_analyzer.py   ← SpecAnalyzer Two-Pass 执行链
  workflow/nodes/llm_utils.py       ← JSON 解析 + CLI 调用
  workflow/spec/spec_analyzer_prompt.py ← Two-Pass 提示词模板
  workflow/spec/codegen_prompt.py   ← CodeGen 提示词模板
```

### 真实案例复盘

| 案例 | 教训 |
|------|------|
| State Merge 白名单→黑名单 | 引擎层不应含业务字段名 |
| LangGraph 内外状态脱节 | `astream` 内部状态独立于外部 copy |
| stream-json result 陷阱 | prompt 必须约束输出方式 |
| 闭包变量捕获 | 循环中的闭包需要通过默认参数绑定 |
| falsy 空列表 | `data.get("key")` 返回 `[]` 是 falsy |

---

## Phase 3: 生产级工程能力（Week 4）

**目标**：掌握 Temporal、SSE 架构、数据库、部署

### 阅读顺序

| 序号 | 文档 | 内容 | 预计时间 |
|------|------|------|----------|
| 1 | [Temporal 持久化工作流实战](./t171-temporal-workflow.md) | Workflow/Activity 模式 + 三层超时 + 心跳 + 状态同步 + Checkpoint | 90 min |
| 2 | [综合练习集](./t173-exercises.md) | 4 个端到端跨层练习（后端→SSE→前端） | 120 min |

### 核心主题

- **Temporal** — Worker、Activity、重试策略、从 asyncio 迁移的原因
- **三层超时模型** — schedule_to_close / start_to_close / heartbeat_timeout
- **SSE 事件架构** — Worker → HTTP POST → EventBus → SSE → 前端消费
- **状态同步** — 增量同步 + 最终同步 + 索引映射
- **Checkpoint 恢复** — 崩溃后断点续传
- **SQLAlchemy async** — Repository 模式、Alembic 迁移
- **Docker 多服务** — Compose 编排、多阶段构建

### 关键文件入口

```
backend/
  workflow/temporal/worker.py       ← Temporal Worker
  workflow/temporal/batch_activities.py ← Activity 定义
  workflow/temporal/spec_activities.py  ← Design-to-Spec Activity
  workflow/temporal/state_sync.py   ← DB 状态同步
  workflow/temporal/sse_events.py   ← SSE 推送 + 心跳
  app/temporal_adapter.py           ← Temporal 客户端适配器
  app/database.py                   ← 数据库连接
  app/repositories/                 ← Repository 模式
  app/event_bus.py                  ← SSE 事件总线

docker-compose.yml                  ← 多服务编排
Dockerfile.backend / Dockerfile.frontend
```

### 真实案例复盘

| 案例 | 教训 |
|------|------|
| asyncio 事件循环饥饿 | tight readline loop 阻塞整个事件循环 → Temporal Worker 隔离 |
| SSE spec recovery | 终态 Job 无事件推送 → 必须有 DB 恢复路径 |
| Mock Patching 懒导入 | patch 位置取决于 import 方式（源模块 vs 调用模块） |
| SQLite 并发写入 | `database is locked` → 指数退避 + 抖动重试 |

---

## Phase 4: 多 Agent 系统 + 综合实战（Week 5-6）

**目标**：理解多 Agent 协作架构，独立开发 feature

### 核心主题

- **MCP (Model Context Protocol)** — Server 实现、Tool 定义
- **CCCC 多 Agent** — Foreman/Peer 模型、消息协议、Context 共享
- **Design-to-Code 全管线** — Figma → Spec → Component Code
- **E2E 测试体系** — Playwright 测试组织、覆盖策略

### 关键文件入口

```
backend/
  workflow/mcp_server/              ← MCP Server 实现
  workflow/spec/                    ← Design-to-Spec 管线
  workflow/agents/                  ← LangGraph Agent

openspec/                           ← OpenSpec SDK
tests/                              ← 测试套件（177+ tests）
e2e/                                ← Playwright E2E 测试
```

### 毕业项目

独立开发一个完整 feature（从需求分析 → 后端 API → 前端 UI → 测试 → 部署），证明你已经掌握全栈 AI 应用开发能力。

---

## 项目技术栈速查

| 层级 | 技术 | 用途 |
|------|------|------|
| AI 编排 | LangGraph | 有状态工作流图 |
| 任务调度 | Temporal | 持久化活动执行 |
| 后端 | FastAPI + SQLAlchemy + Pydantic | REST API + SSE + DB |
| 前端 | Next.js 14 + React 18 + Tailwind | App Router + SSE 消费 |
| AI 集成 | Claude CLI (stream-json) | Agent 调用封装 |
| 部署 | Docker Compose | 多服务容器编排 |
| 协作 | CCCC | 多 Agent 协作框架 |

---

## 启动开发环境

```bash
# 根目录一键启动
make dev

# 分开启动（多终端）
# 终端 1: 后端
cd backend && make dev

# 终端 2: 前端
cd frontend && npm run dev
```

- FastAPI: http://localhost:8000
- Next.js: http://localhost:3000
- Temporal: http://localhost:7233
