# Work-Flow

[English](#english) | [中文](#中文)

---

<a id="english"></a>

## English

An open-source developer workflow platform that automates repetitive engineering tasks using **Claude AI** + **Temporal** + **LangGraph**.

### What It Does

**Two production pipelines:**

| Pipeline | Input | Output | How It Works |
|----------|-------|--------|--------------|
| **Batch Bug Fix** | Jira URLs | Git PRs with fixes | Jira fetch → Claude CLI analysis → code fix → verification → Git branch + PR |
| **Design-to-Spec** | Figma URL | `design_spec.json` | Figma API scan → frame classification → two-pass SpecAnalyzer (LLM vision) → structured spec |

Both pipelines run as durable Temporal workflows with real-time SSE progress streaming.

### Tech Stack

| Layer | Technology |
|-------|-----------|
| Frontend | Next.js 14, React Flow, shadcn/ui, Tailwind CSS |
| Backend | FastAPI, SQLAlchemy (async), Pydantic v2 |
| Orchestration | Temporal (durable workflows), LangGraph (DAG execution) |
| AI | Claude CLI (code generation), Claude API (vision analysis) |
| Database | SQLite (aiosqlite) — PostgreSQL ready |
| Testing | pytest (624 tests), Vitest, Playwright |

### Quick Start

#### Option A: Local Development

**Prerequisites:** Python 3.11+, Node.js 18+, [Temporal CLI](https://docs.temporal.io/cli)

```bash
# Clone
git clone https://github.com/your-org/work-flow.git
cd work-flow

# Backend
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -e ".[test]"
make dev    # Starts Temporal + Worker + FastAPI on :8000

# Frontend (new terminal)
cd frontend
npm install
npm run dev  # Starts Next.js on :3000
```

#### Option B: Docker Compose

```bash
cp .env.example .env
# Edit .env — set FIGMA_TOKEN, JIRA_* if needed
docker compose up --build
```

Services: backend `:8000`, frontend `:3000`, Temporal `:7233` (Web UI `:8080`)

Open http://localhost:3000

### Configuration

Copy `.env.example` to `.env` and configure:

| Variable | Required | Description |
|----------|----------|-------------|
| `ANTHROPIC_API_KEY` | For AI features | Claude API key |
| `FIGMA_TOKEN` | For Design-to-Spec | Figma Personal Access Token |
| `JIRA_URL` | For Batch Bug Fix | Jira instance URL |
| `JIRA_EMAIL` | For Batch Bug Fix | Jira account email |
| `JIRA_API_TOKEN` | For Batch Bug Fix | Jira API token |
| `CLAUDE_CLI_PATH` | Auto-detected | Path to `claude` CLI binary |

### Project Structure

```
work-flow/
├── backend/
│   ├── app/                    # FastAPI application
│   │   ├── routes/             # API endpoints (batch, design, workflows)
│   │   ├── repositories/       # Data access layer
│   │   ├── models/             # SQLAlchemy ORM models
│   │   ├── database.py         # DB engine + session management
│   │   ├── event_bus.py        # Unified SSE event infrastructure
│   │   └── temporal_adapter.py # Temporal client singleton
│   ├── workflow/
│   │   ├── engine/             # LangGraph graph builder + executor
│   │   ├── nodes/              # Node type registry (agents, spec_analyzer, etc.)
│   │   ├── temporal/           # Temporal workflows + activities
│   │   ├── integrations/       # Figma client, classifiers
│   │   └── templates/          # Workflow JSON templates
│   ├── tests/                  # 624 tests (pytest)
│   ├── Makefile                # dev/stop/worker/api/temporal
│   └── pyproject.toml
├── frontend/
│   ├── app/
│   │   ├── batch-bugs/         # Batch Bug Fix UI
│   │   ├── design-to-code/     # Design-to-Spec UI
│   │   └── workflows/          # Visual workflow editor
│   ├── components/             # Shared UI components (shadcn/ui)
│   └── lib/                    # Hooks, utilities
├── docker-compose.yml          # 3-service stack
├── Dockerfile.backend          # Multi-stage Python build
├── Dockerfile.frontend         # Next.js standalone build
└── .env.example                # Environment template
```

### API Endpoints

#### Batch Bug Fix

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/v2/batch/bug-fix` | Create batch job (or dry-run with `dry_run: true`) |
| GET | `/api/v2/batch/bug-fix` | List jobs (pagination, status filter) |
| GET | `/api/v2/batch/bug-fix/{job_id}` | Job status + bug details |
| GET | `/api/v2/batch/bug-fix/{job_id}/stream` | SSE event stream |
| POST | `/api/v2/batch/bug-fix/{job_id}/cancel` | Cancel running job |
| POST | `/api/v2/batch/bug-fix/{job_id}/retry/{bug_index}` | Retry failed bug |
| DELETE | `/api/v2/batch/bug-fix/{job_id}` | Delete job |
| GET | `/api/v2/batch/metrics/job/{job_id}` | Job metrics |
| GET | `/api/v2/batch/metrics/global` | Global metrics |

#### Design-to-Spec

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/v2/design/scan-figma` | Scan Figma page, classify frames |
| POST | `/api/v2/design/run-spec` | Start spec generation pipeline |
| GET | `/api/v2/design/{job_id}` | Job status |
| GET | `/api/v2/design/{job_id}/stream` | SSE event stream |
| GET | `/api/v2/design/{job_id}/files` | Generated spec files |
| GET | `/api/v2/design` | List jobs |
| POST | `/api/v2/design/{job_id}/cancel` | Cancel job |

#### Visual Workflows

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/v2/workflows` | List workflows |
| POST | `/api/v2/workflows` | Create workflow |
| POST | `/api/v2/workflows/{id}/run` | Execute workflow |
| GET | `/api/v2/sse/stream/{run_id}` | SSE event stream |

### Testing

```bash
cd backend

# All tests
python -m pytest tests/ -q

# By module
python -m pytest tests/test_routes_batch.py -q       # 34 route tests
python -m pytest tests/test_routes_design.py -q       # 22 route tests
python -m pytest tests/test_repository_batch_job.py -q # 28 repo tests
python -m pytest tests/workflow/ -q                    # Workflow engine tests
```

### Architecture

```
[Browser] ──→ [Next.js :3000] ──→ [FastAPI :8000] ──→ [Temporal :7233]
                                        │                     │
                                   [SQLite DB]          [Worker Process]
                                        │                     │
                                   [EventBus] ←── SSE ──── [Activities]
                                        │                     │
                                   [SSE Stream] ←──────── [Claude CLI / Figma API]
```

---

<a id="中文"></a>

## 中文

开源的开发者工作流平台，使用 **Claude AI** + **Temporal** + **LangGraph** 自动化重复性工程任务。

### 核心功能

**两条生产管线：**

| 管线 | 输入 | 输出 | 工作方式 |
|------|------|------|----------|
| **批量修 Bug** | Jira URL 列表 | Git PR（含修复） | Jira 获取 → Claude CLI 分析 → 代码修复 → 验证 → Git 分支 + PR |
| **设计转 Spec** | Figma URL | `design_spec.json` | Figma API 扫描 → 帧分类 → 两轮 SpecAnalyzer（LLM 视觉分析） → 结构化规格 |

两条管线均以 Temporal 持久化工作流运行，支持实时 SSE 进度推送。

### 技术栈

| 层级 | 技术 |
|------|-----|
| 前端 | Next.js 14, React Flow, shadcn/ui, Tailwind CSS |
| 后端 | FastAPI, SQLAlchemy (async), Pydantic v2 |
| 编排 | Temporal（持久化工作流）, LangGraph（DAG 执行） |
| AI | Claude CLI（代码生成）, Claude API（视觉分析） |
| 数据库 | SQLite (aiosqlite) — 可切换 PostgreSQL |
| 测试 | pytest（624 个测试）, Vitest, Playwright |

### 快速启动

#### 方式 A：本地开发

**前置条件：** Python 3.11+、Node.js 18+、[Temporal CLI](https://docs.temporal.io/cli)

```bash
# 克隆
git clone https://github.com/your-org/work-flow.git
cd work-flow

# 后端
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -e ".[test]"
make dev    # 一键启动 Temporal + Worker + FastAPI（:8000）

# 前端（新开终端）
cd frontend
npm install
npm run dev  # 启动 Next.js（:3000）
```

#### 方式 B：Docker Compose

```bash
cp .env.example .env
# 编辑 .env — 按需设置 FIGMA_TOKEN、JIRA_* 等
docker compose up --build
```

服务：后端 `:8000`、前端 `:3000`、Temporal `:7233`（Web UI `:8080`）

打开 http://localhost:3000

### 配置说明

将 `.env.example` 复制为 `.env` 并配置：

| 变量 | 是否必需 | 说明 |
|------|----------|------|
| `ANTHROPIC_API_KEY` | AI 功能需要 | Claude API 密钥 |
| `FIGMA_TOKEN` | 设计转 Spec 需要 | Figma 个人访问令牌 |
| `JIRA_URL` | 批量修 Bug 需要 | Jira 实例地址 |
| `JIRA_EMAIL` | 批量修 Bug 需要 | Jira 账号邮箱 |
| `JIRA_API_TOKEN` | 批量修 Bug 需要 | Jira API 令牌 |
| `CLAUDE_CLI_PATH` | 自动检测 | `claude` CLI 二进制路径 |

### 项目结构

```
work-flow/
├── backend/
│   ├── app/                    # FastAPI 应用
│   │   ├── routes/             # API 端点（batch, design, workflows）
│   │   ├── repositories/       # 数据访问层
│   │   ├── models/             # SQLAlchemy ORM 模型
│   │   ├── database.py         # 数据库引擎 + 会话管理
│   │   ├── event_bus.py        # 统一 SSE 事件基础设施
│   │   └── temporal_adapter.py # Temporal 客户端单例
│   ├── workflow/
│   │   ├── engine/             # LangGraph 图构建器 + 执行器
│   │   ├── nodes/              # 节点类型注册（agents, spec_analyzer 等）
│   │   ├── temporal/           # Temporal 工作流 + 活动
│   │   ├── integrations/       # Figma 客户端、分类器
│   │   └── templates/          # 工作流 JSON 模板
│   ├── tests/                  # 624 个测试（pytest）
│   ├── Makefile                # dev/stop/worker/api/temporal
│   └── pyproject.toml
├── frontend/
│   ├── app/
│   │   ├── batch-bugs/         # 批量修 Bug 界面
│   │   ├── design-to-code/     # 设计转 Spec 界面
│   │   └── workflows/          # 可视化工作流编辑器
│   ├── components/             # 共享 UI 组件（shadcn/ui）
│   └── lib/                    # Hooks、工具函数
├── docker-compose.yml          # 3 服务编排
├── Dockerfile.backend          # 多阶段 Python 构建
├── Dockerfile.frontend         # Next.js standalone 构建
└── .env.example                # 环境变量模板
```

### 测试

```bash
cd backend

# 全量测试
python -m pytest tests/ -q

# 按模块
python -m pytest tests/test_routes_batch.py -q       # 34 个路由测试
python -m pytest tests/test_routes_design.py -q       # 22 个路由测试
python -m pytest tests/test_repository_batch_job.py -q # 28 个仓储测试
python -m pytest tests/workflow/ -q                    # 工作流引擎测试
```

### 架构

```
[浏览器] ──→ [Next.js :3000] ──→ [FastAPI :8000] ──→ [Temporal :7233]
                                       │                     │
                                  [SQLite DB]          [Worker 进程]
                                       │                     │
                                  [EventBus] ←── SSE ──── [Activities]
                                       │                     │
                                  [SSE 推送] ←──────── [Claude CLI / Figma API]
```

### License

MIT
