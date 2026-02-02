# Dynamic Workflow Platform

[English](#english) | [中文](#中文)

---

<a id="english"></a>

## English

A visual workflow orchestration platform powered by **LangGraph** + **Temporal**, with a drag-and-drop editor and real-time execution monitoring.

### Features

- Visual workflow editor (React Flow) with drag-and-drop node composition
- Dual execution engine: LangGraph for dynamic DAG execution, Temporal for durable orchestration
- Multiple node types: Data Source, Processor, HTTP Request, Condition, LLM Agent, CCCC Peer, Output
- Loop support with configurable max iterations and graceful termination
- Real-time SSE event streaming for execution status
- Multi-agent collaboration via CCCC protocol

### Tech Stack

| Layer | Technology |
|-------|-----------|
| Frontend | Next.js, React Flow, shadcn/ui, Tailwind CSS |
| Backend | FastAPI, SQLAlchemy (async), Alembic |
| Workflow | LangGraph, Temporal |
| Database | SQLite (aiosqlite) |

### Quick Start

**Prerequisites:** Python 3.10+, Node.js 18+, [Temporal CLI](https://docs.temporal.io/cli)

```bash
# 1. Backend (Temporal + Worker + FastAPI, all-in-one)
cd backend_fastapi
python -m venv .venv
source .venv/bin/activate
pip install -e .
make dev

# 2. Frontend (in a new terminal)
cd frontend
npm install
npm run dev
```

Open http://localhost:3000 to access the workflow editor.

To stop all backend services:

```bash
cd backend_fastapi
make stop
```

### Project Structure

```
backend_fastapi/     # FastAPI backend + workflow engine
  app/               # FastAPI application (routes, models, DB)
  workflow/           # Workflow engine core
    engine/           # Graph builder, executor, expression evaluator
    nodes/            # Node type registry (data_source, llm_agent, etc.)
    temporal/         # Temporal workflows, activities, worker
    agents/           # Agent integrations (LLM, CCCC)
    sse/              # Server-Sent Events infrastructure
frontend/            # Next.js workflow editor UI
```

### API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/v2/workflows` | List workflows |
| GET | `/api/v2/workflows/{id}` | Get workflow detail |
| POST | `/api/v2/workflows` | Create workflow |
| PUT | `/api/v2/workflows/{id}` | Update workflow |
| POST | `/api/v2/workflows/{id}/run` | Execute workflow |
| GET | `/api/v2/workflows/{id}/runs` | List run history |
| GET | `/api/v2/sse/stream/{run_id}` | SSE event stream |

---

<a id="中文"></a>

## 中文

基于 **LangGraph** + **Temporal** 的可视化工作流编排平台，支持拖拽式编辑器和实时执行监控。

### 功能特性

- 可视化工作流编辑器（React Flow），支持拖拽节点组合
- 双引擎执行：LangGraph 负责动态 DAG 执行，Temporal 负责持久化编排
- 多种节点类型：数据源、处理器、HTTP 请求、条件判断、LLM Agent、CCCC Peer、输出
- 循环支持：可配置最大迭代次数，超限后优雅终止
- 实时 SSE 事件流推送执行状态
- 通过 CCCC 协议实现多智能体协作

### 技术栈

| 层级 | 技术 |
|------|-----|
| 前端 | Next.js, React Flow, shadcn/ui, Tailwind CSS |
| 后端 | FastAPI, SQLAlchemy (async), Alembic |
| 工作流 | LangGraph, Temporal |
| 数据库 | SQLite (aiosqlite) |

### 快速启动

**前置条件：** Python 3.10+、Node.js 18+、[Temporal CLI](https://docs.temporal.io/cli)

```bash
# 1. 后端（Temporal + Worker + FastAPI 一键启动）
cd backend_fastapi
python -m venv .venv
source .venv/bin/activate
pip install -e .
make dev

# 2. 前端（新开一个终端）
cd frontend
npm install
npm run dev
```

打开 http://localhost:3000 即可访问工作流编辑器。

停止所有后端服务：

```bash
cd backend_fastapi
make stop
```

### 项目结构

```
backend_fastapi/     # FastAPI 后端 + 工作流引擎
  app/               # FastAPI 应用（路由、模型、数据库）
  workflow/           # 工作流引擎核心
    engine/           # 图构建器、执行器、表达式求值
    nodes/            # 节点类型注册（data_source, llm_agent 等）
    temporal/         # Temporal 工作流、活动、Worker
    agents/           # Agent 集成（LLM、CCCC）
    sse/              # Server-Sent Events 基础设施
frontend/            # Next.js 工作流编辑器 UI
```

### API 接口

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v2/workflows` | 工作流列表 |
| GET | `/api/v2/workflows/{id}` | 工作流详情 |
| POST | `/api/v2/workflows` | 创建工作流 |
| PUT | `/api/v2/workflows/{id}` | 更新工作流 |
| POST | `/api/v2/workflows/{id}/run` | 执行工作流 |
| GET | `/api/v2/workflows/{id}/runs` | 运行记录 |
| GET | `/api/v2/sse/stream/{run_id}` | SSE 事件流 |
