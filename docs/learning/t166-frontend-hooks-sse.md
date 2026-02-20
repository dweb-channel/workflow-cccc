# T166: 前端核心 Hook + SSE 模式走读

> **作者**: code-simplifier (前端专家)
> **目标读者**: 想要成为高级 AI 应用开发工程师的你
> **前置要求**: 基本了解 React、TypeScript 语法

---

## 目录

1. [S1: 核心 Hook 逐行解读](#s1-核心-hook-逐行解读)
2. [S2: Next.js App Router 项目结构](#s2-nextjs-app-router-项目结构)
3. [S3: 组件拆分最佳实践](#s3-组件拆分最佳实践)

---

## S1: 核心 Hook 逐行解读

### 1.1 整体架构：三层 SSE 抽象

本项目的前端实时通信采用了**三层抽象**设计，从底层到高层：

```
useSSEStream          ← 通用 SSE 连接管理（EventSource + 重连 + 心跳）
  └── usePipelineConnection  ← Pipeline 生命周期门控（终态 Job 不连接）
        ├── useDesignJob      ← Design-to-Code 管线业务逻辑
        └── useBatchJob       ← Batch Bug Fix 管线业务逻辑
```

**设计原则**: 每一层只做一件事，层与层之间通过 TypeScript 接口解耦。

---

### 1.2 底层：useSSEStream — 通用 SSE 连接管理

**文件**: `frontend/lib/useSSEStream.ts`

这是整个 SSE 体系的基石。它解决了浏览器 `EventSource` API 的几个生产级问题：

#### 核心参数

```typescript
export interface UseSSEStreamOptions {
  url: string | null | undefined;     // null = 不连接
  handlers: Record<string, (data) => void>; // 事件类型 → 处理函数
  terminalEvents?: string[];           // 终止事件（如 "job_done"）
  pollFn?: () => Promise<void>;        // 降级轮询
  heartbeatTimeoutMs?: number;         // 心跳超时（默认 60s）
  backoffBaseMs?: number;              // 重连基础间隔
}
```

#### 关键设计点

**1) URL 驱动连接生命周期**

```typescript
// useSSEStream.ts:130-135
useEffect(() => {
  if (!url) {
    setConnected(false);
    setStale(false);
    return;
  }
  // ... 创建 EventSource
}, [url, ...]);
```

- `url` 为 `null` → 不连接，清理状态
- `url` 有值 → 创建 `EventSource` 连接
- `url` 变化 → effect 清理旧连接，建立新连接

这是 React 的 **声明式副作用** 模式：你不需要手动 `connect()` / `disconnect()`，只需要改变 `url` 的值。

**2) Ref 存储回调，避免无限重连**

```typescript
// useSSEStream.ts:108-122
const handlersRef = useRef(options.handlers);
handlersRef.current = options.handlers;

const pollFnRef = useRef(options.pollFn);
pollFnRef.current = options.pollFn;
```

为什么用 `useRef` 而不是直接放进 `useEffect` 依赖数组？

- `handlers` 对象每次渲染都可能是新引用（即使内容相同）
- 如果放在 `useEffect` 依赖里，每次渲染都会**断开重连** SSE
- 用 Ref 存最新值，`useEffect` 内通过 `handlersRef.current` 访问
- 结果：**handlers 可以随时更新，但不会触发重连**

> **学习要点**: 这是 React Hooks 中非常常见的 "Latest Ref" 模式。当你需要在 effect 中访问最新值但又不想让它成为依赖时，用 Ref。

**3) 指数退避重连**

```typescript
// useSSEStream.ts:213-234
es.onerror = () => {
  // ...
  const delay = getBackoffMs(retryCountRef.current, backoffBaseMs, backoffMaxMs);
  retryCountRef.current++;
  retryTimer = setTimeout(connect, delay);
};
```

退避公式：`min(baseMs * 2^retryCount, maxMs)`

```
第1次重连: 3s
第2次重连: 6s
第3次重连: 12s
第4次重连: 24s
第5次+: 30s（封顶）
```

**4) 心跳超时检测**

```typescript
// useSSEStream.ts:154-161
const resetHeartbeat = () => {
  clearHeartbeat();
  setStale(false);
  heartbeatTimerRef.current = setTimeout(() => {
    setStale(true);
  }, heartbeatTimeoutMs);
};
```

- 每收到一个 SSE 事件就重置定时器
- 如果 60 秒没收到任何事件 → `stale = true`
- UI 可以据此显示 "连接可能不稳定" 的提示

**5) 终止事件自动断连**

```typescript
// useSSEStream.ts:204-209
if (terminalEventsRef.current.includes(eventType)) {
  closedIntentionallyRef.current = true;  // 标记：主动关闭
  es.close();
  setConnected(false);
}
```

- 收到 `job_done` 等终止事件后自动关闭 EventSource
- `closedIntentionallyRef` 防止 `onerror` 触发无意义的重连

**6) 降级轮询（双保险）**

```typescript
// useSSEStream.ts:241-245
pollTimer = setInterval(() => {
  pollFnRef.current?.().catch(() => {});
}, pollIntervalMs);
```

即使 SSE 连接正常，也每 30 秒轮询一次作为兜底。这确保了即使 SSE 丢事件，UI 状态最终也能同步。

---

### 1.3 中间层：usePipelineConnection — 生命周期门控

**文件**: `frontend/lib/usePipelineConnection.ts`

这层只有 ~30 行，但解决了一个关键问题：**已完成的 Job 不应该创建 SSE 连接**。

```typescript
const sseUrl = useMemo(() => {
  if (!jobId || !jobStatus || TERMINAL_STATUSES.includes(jobStatus)) {
    return null;  // → useSSEStream 不会连接
  }
  return getStreamUrl(jobId);
}, [jobId, jobStatus, getStreamUrl]);
```

`TERMINAL_STATUSES = ["completed", "failed", "cancelled"]`

- Job 还没开始 → `jobId` 为空 → `url = null` → 不连接
- Job 正在运行 → 返回 SSE URL → 自动连接
- Job 已完成 → `url = null` → 自动断开

> **设计原则**: 分层的好处 — `useSSEStream` 不需要知道什么是 "Job"，`usePipelineConnection` 不需要知道 EventSource 怎么重连。

---

### 1.4 业务层：useDesignJob 详解

**文件**: `frontend/app/design-to-code/hooks/useDesignJob.ts`

这是 Design-to-Code 管线的完整状态管理 Hook。我们逐块解析：

#### 状态声明（L22-30）

```typescript
const [currentJob, setCurrentJob] = useState<DesignJob | null>(null);
const [designSpec, setDesignSpec] = useState<DesignSpec | null>(null);
const [specComplete, setSpecComplete] = useState(false);
const [events, setEvents] = useState<PipelineEvent[]>([]);
```

| 状态 | 类型 | 职责 |
|------|------|------|
| `currentJob` | `DesignJob \| null` | 当前 Job 元数据（ID、状态、组件计数） |
| `designSpec` | `DesignSpec \| null` | 设计规格（组件列表，渐进式填充） |
| `specComplete` | `boolean` | Spec 分析是否完成 |
| `events` | `PipelineEvent[]` | 事件流（用于 ActivityFeed 渲染） |
| `tokenUsage` | `{input, output}` | Token 消耗统计 |

#### 恢复逻辑（L33-58）— 页面刷新后恢复 Job

```typescript
useEffect(() => {
  const controller = new AbortController();
  (async () => {
    const activeJob = await getActiveDesignJob();
    if (controller.signal.aborted || !activeJob) return;
    setCurrentJob({ /* ... */ });
  })();
  return () => controller.abort();
}, []);
```

**要点**:
- 组件挂载时检查是否有未完成的 Job（后端 `GET /api/v2/design/active`）
- `AbortController` 防止组件卸载后还设置状态（避免 React 警告）
- 空依赖 `[]` 表示只在挂载时执行一次

#### Spec 恢复逻辑（L60-86）— 已完成 Job 恢复 designSpec

```typescript
useEffect(() => {
  if (!currentJob?.job_id || !currentJob.design_file || designSpec) return;
  if (!["completed", "running", "started"].includes(currentJob.job_status)) return;
  // ... fetch spec from backend
}, [currentJob?.job_id, currentJob?.job_status, currentJob?.design_file, designSpec]);
```

这个 effect 解决了一个真实 Bug（本项目 M30 修复）：

```
用户回到已完成的 Job
  → designSpec 初始为 null
  → SSE 连接建立但 Job 已完成，不会推送事件
  → designSpec 保持 null → UI 显示 "No design spec"
  → 修复：从后端 REST API 恢复 spec 数据
```

> **踩坑教训**: 不能只靠实时流（SSE）填充状态，必须有**恢复路径**（REST API 回读）。

#### SSE 事件处理器（L137-318）— 核心业务逻辑

事件处理器用 `useMemo` 包裹，依赖 `[pushEvent]`：

```typescript
const sseHandlers = useMemo<Record<string, (data) => void>>(() => ({
  job_state: (data) => { /* 更新 Job 元数据 */ },
  node_started: (data) => { /* 标记当前运行节点 */ },
  frame_decomposed: (data) => { /* 渐进式填充 designSpec */ },
  spec_analyzed: (data) => { /* 更新单个组件的分析结果 */ },
  spec_complete: (data) => { /* 标记完成 */ },
  job_done: (data) => { /* 最终状态更新 */ },
}), [pushEvent]);
```

**SSE 事件 → UI 状态映射表**:

| SSE 事件 | UI 状态变化 | 用户看到什么 |
|----------|------------|------------|
| `job_state` | `currentJob.job_status` 更新 | 顶部状态标签变化 |
| `node_started` | `currentNode` 设为当前节点 | Pipeline 进度条高亮 |
| `frame_decomposed` | `designSpec.components` 填充 | Spec 面板出现组件卡片 |
| `spec_analyzed` | 单个组件的 `role/description` 更新 | 卡片内容渐进丰富 |
| `spec_complete` | `specComplete = true` | 出现完成标记 |
| `job_done` | Job 进入终态 | SSE 断连，显示完成 |

#### 渐进式 Spec 构建 — `frame_decomposed` 处理器

```typescript
frame_decomposed: (data) => {
  const components = data.components as ComponentSpec[];
  setDesignSpec((prev) => {
    if (!prev) {
      // 首次：创建新 DesignSpec
      return { version: "1.0", source: ..., components };
    }
    // 后续：合并（按 id 去重）
    const merged = [...prev.components];
    for (const comp of components) {
      const idx = merged.findIndex((c) => c.id === comp.id);
      if (idx >= 0) merged[idx] = { ...merged[idx], ...comp };
      else merged.push(comp);
    }
    return { ...prev, components: merged };
  });
};
```

这是**渐进式渲染**模式：后端每分析完一个组件就推送一次，前端逐步合并，用户能实时看到组件一个个 "冒出来"。

#### 事件限流（L114-118）

```typescript
setEvents((prev) => {
  const next = [...prev, evt];
  if (next.length > MAX_EVENTS) return next.slice(next.length - TRIM_TO);
  return next;
});
```

- `MAX_EVENTS = 500`, `TRIM_TO = 300`
- 当事件超过 500 条时，截断到最新 300 条
- 防止长时间运行的 Job 导致内存泄漏

---

### 1.5 业务层：useBatchJob 对比分析

**文件**: `frontend/app/batch-bugs/hooks/useBatchJob.ts`

与 `useDesignJob` 的架构完全对称，但业务状态不同：

| 维度 | useDesignJob | useBatchJob |
|------|-------------|-------------|
| 核心状态 | `designSpec`（渐进式 Spec） | `bugs[]`（每个 Bug 的状态+步骤） |
| 细粒度事件 | `spec_analyzed`（组件级） | `bug_step_started/completed`（步骤级） |
| 特有功能 | token 统计 | 重试单个 Bug、AI Thinking 面板 |
| 恢复逻辑 | Spec 文件回读 | Bug 列表回读 |

**useBatchJob 独有的设计模式**:

**1) updateBug — 按索引更新单个 Bug**

```typescript
const updateBug = useCallback(
  (bugIndex: number, updater: (bug: BugStatus) => BugStatus) => {
    setCurrentJob((prev) =>
      prev ? {
        ...prev,
        bugs: prev.bugs.map((bug, idx) =>
          idx === bugIndex ? updater(bug) : bug
        ),
      } : prev
    );
  }, []
);
```

这是**函数式状态更新**模式 — 传入 updater 函数而非新值，确保总是基于最新状态修改。

**2) Toast Ref — 避免回调依赖变化**

```typescript
const toastRef = useRef(toast);
toastRef.current = toast;
// 在 SSE 回调中用 toastRef.current 而非 toast
```

与 `useSSEStream` 中 `handlersRef` 的 "Latest Ref" 模式相同。

**3) 步骤匹配的逆序查找**

```typescript
// bug_step_completed 处理器
for (let i = steps.length - 1; i >= 0; i--) {
  if (steps[i].step === data.step && steps[i].status === "in_progress") {
    steps[i] = { ...steps[i], status: "completed", ... };
    found = true;
    break;
  }
}
```

为什么从后往前找？因为同一个步骤可能因重试而出现多次，我们要匹配**最近的**那个 `in_progress` 步骤。

---

## S2: Next.js App Router 项目结构

### 2.1 目录组织

```
frontend/
├── app/                          # Next.js App Router 根
│   ├── layout.tsx               # 根布局（Sidebar + ThemeProvider）
│   ├── page.tsx                 # 首页（/）
│   ├── globals.css              # 全局样式 + CSS 变量（dark/light）
│   ├── batch-bugs/              # 批量 Bug 修复（/batch-bugs）
│   │   ├── page.tsx             # 页面入口
│   │   ├── types.ts             # 类型定义
│   │   ├── hooks/               # 业务 Hooks
│   │   │   ├── useBatchJob.ts
│   │   │   ├── useJobHistory.ts
│   │   │   └── useWorkspaces.ts
│   │   └── components/          # 业务组件
│   │       ├── ActivityFeed.tsx
│   │       ├── BugInput.tsx
│   │       ├── PipelineBar.tsx
│   │       └── ...
│   ├── design-to-code/          # Design-to-Code（/design-to-code）
│   │   ├── page.tsx
│   │   ├── types.ts
│   │   ├── hooks/
│   │   └── components/
│   └── canvas/                  # 工作流画布编辑器（/canvas）
├── components/                   # 共享组件
│   ├── ui/                      # shadcn/ui 基础组件
│   ├── sidebar/                 # Sidebar 组件
│   └── theme-provider.tsx       # 主题切换
├── lib/                          # 共享工具库
│   ├── api.ts                   # API 客户端（REST 调用）
│   ├── useSSEStream.ts          # 通用 SSE Hook
│   ├── usePipelineConnection.ts # Pipeline SSE 门控
│   ├── constants.ts             # 共享常量
│   └── types/                   # 共享类型
└── public/                       # 静态资源
```

### 2.2 App Router 关键概念

#### 路由 = 文件系统

```
app/page.tsx             → /
app/batch-bugs/page.tsx  → /batch-bugs
app/design-to-code/page.tsx → /design-to-code
app/canvas/page.tsx      → /canvas
```

每个 `page.tsx` 就是一个页面路由，**不需要配置路由表**。

#### Layout 嵌套

```typescript
// app/layout.tsx — 所有页面共享
export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="zh-CN" suppressHydrationWarning>
      <body>
        <ThemeProvider>
          <div className="flex h-screen overflow-hidden">
            <Sidebar />                {/* 所有页面都有 Sidebar */}
            <main className="flex-1">
              {children}               {/* 具体页面内容 */}
            </main>
          </div>
          <Toaster />                  {/* 全局 Toast */}
        </ThemeProvider>
      </body>
    </html>
  );
}
```

Layout 自动嵌套：子路由的 `page.tsx` 会渲染在父 Layout 的 `{children}` 位置。

#### Client vs Server 组件

```typescript
// 所有含 useState/useEffect 的组件必须标记：
"use client";  // ← 文件顶部

// 没有这个标记的组件默认是 Server Component
// Server Component 不能用 Hooks，但可以 async/await
```

**本项目的模式**：
- `layout.tsx` — Server Component（可以是 async）
- `page.tsx` — 通常标记 `"use client"`（因为用了 Hooks）
- `hooks/` — 全部 `"use client"`
- `components/ui/` — 按需标记

### 2.3 主题切换实现

```typescript
// layout.tsx 中的闪烁防护脚本
<script dangerouslySetInnerHTML={{
  __html: `
    (function() {
      var theme = localStorage.getItem('theme');
      if (theme === 'dark') {
        document.documentElement.classList.add('dark');
      }
    })();
  `
}} />
```

为什么需要内联脚本？因为 React 水合（hydration）发生在 JS 加载之后，如果不提前设置 `dark` class，用户会看到**白色闪烁**（FOUC）。

CSS 变量方案：

```css
/* globals.css */
:root {
  --background: 0 0% 100%;    /* 浅色 */
  --foreground: 0 0% 3.9%;
}
.dark {
  --background: 0 0% 3.9%;    /* 深色 */
  --foreground: 0 0% 98%;
}
```

所有组件使用 `bg-background`、`text-foreground` 等 Tailwind 类，自动跟随主题切换。

---

## S3: 组件拆分最佳实践

### 3.1 案例：batch-bugs/page.tsx 拆分（M27 里程碑）

**问题**: `page.tsx` 从最初 ~100 行膨胀到 ~1500 行，包含：
- 3 个自定义 Hook（状态管理）
- 10+ 个内联子组件
- 类型定义
- 辅助函数

**拆分策略**:

```
拆分前:
  page.tsx (1500行)

拆分后:
  page.tsx (200行)         ← 只做布局编排
  types.ts                  ← 类型定义
  hooks/
    useBatchJob.ts          ← 核心状态 + SSE
    useJobHistory.ts        ← 历史记录
    useWorkspaces.ts        ← 工作区管理
  components/
    BugInput.tsx            ← Bug URL 输入
    ConfigOptions.tsx       ← 配置选项
    OverviewTab.tsx         ← 概览面板
    ActivityFeed.tsx        ← 事件流面板
    PipelineBar.tsx         ← 进度条
    HistoryCard.tsx         ← 历史卡片
    MetricsTab.tsx          ← 指标面板
    WorkspacePanel.tsx      ← 工作区面板
```

### 3.2 拆分原则

**1) 类型先行**

先把所有 `interface` / `type` 提到 `types.ts`，这一步零风险：

```typescript
// types.ts
export interface BugStatus {
  bug_id: string;
  url: string;
  status: "pending" | "in_progress" | "completed" | "failed" | "skipped";
  error?: string;
  steps?: BugStep[];
}
```

**2) Hook 按领域提取**

一个 Hook 管理一个领域的状态：

```
useBatchJob    → Job 生命周期 + SSE 事件
useJobHistory  → 历史列表查询
useWorkspaces  → 工作区 CRUD
```

判断标准：如果两组状态之间**没有直接的 setter 交叉引用**，就可以拆成独立 Hook。

**3) 组件按 UI 区域提取**

```typescript
// 拆分后的 page.tsx 只做编排
export default function BatchBugsPage() {
  const job = useBatchJob();
  const history = useJobHistory();

  return (
    <div className="flex h-full">
      <LeftPanel>
        <BugInput onSubmit={job.submit} />
        <ConfigOptions />
      </LeftPanel>
      <RightPanel>
        <OverviewTab stats={job.stats} />
        <ActivityFeed events={job.events} />
      </RightPanel>
    </div>
  );
}
```

**4) 避免过度拆分**

- 只在一个地方使用的 10 行组件 → 不拆
- 只有 2-3 个 state 的小 Hook → 不拆
- 判断标准：**文件超过 300 行**或**职责超过两个**时才拆

### 3.3 拆分时的常见坑

**1) 循环依赖**

```
# 错误: A 导入 B，B 导入 A
components/ActivityFeed.tsx → imports from types.ts
types.ts → imports from components/ActivityFeed.tsx  ← 循环!

# 正确: 类型定义放在独立文件，组件单向依赖
types.ts ← ActivityFeed.tsx
         ← OverviewTab.tsx
```

**2) Props drilling vs Context**

拆分后可能出现需要层层传递 props 的情况：

```typescript
// 不好：层层传递
<Page>
  <Panel job={job}>
    <Card job={job}>
      <Button onClick={job.retry} />  // job 传了 3 层
    </Card>
  </Panel>
</Page>
```

本项目的解决方式：**保持 page.tsx 作为唯一的 "接线板"**，所有 Hook 在 page.tsx 调用，然后把具体属性传给子组件（而非整个 Hook 返回值）。

**3) "use client" 传染**

一个 Server Component 导入了 `"use client"` 组件是没问题的。但如果你在 Server Component 文件里直接写了 `useState`，就必须加 `"use client"` 标记，整个文件变成 Client Component。

---

## 总结：前端 AI 应用的关键模式

| 模式 | 解决什么问题 | 本项目实例 |
|------|------------|-----------|
| SSE 三层抽象 | 复用连接管理，解耦业务 | useSSEStream → usePipelineConnection → useDesignJob |
| Latest Ref | Effect 访问最新值不触发重连 | handlersRef, pollFnRef, toastRef |
| 声明式连接 | URL 变化驱动连接/断开 | `url = null` 即断连 |
| 渐进式渲染 | AI 输出实时展示 | frame_decomposed → spec_analyzed → spec_complete |
| 恢复路径 | 页面刷新后状态不丢失 | mount recovery + spec file recovery |
| 事件限流 | 长时间 Job 防内存泄漏 | MAX_EVENTS=500, TRIM_TO=300 |
| 函数式更新 | 避免状态竞态 | `setCurrentJob(prev => ...)` 而非 `setCurrentJob(newValue)` |

---

## 练习建议

1. **走读 useSSEStream.ts**：画出 EventSource 的状态机（打开 → 收到事件 → 错误 → 重连 → 终止）
2. **对比两个业务 Hook**：找出 useDesignJob 和 useBatchJob 的结构相似点和差异点
3. **尝试添加一个新的 SSE 事件类型**：比如在 useDesignJob 中处理一个假设的 `component_generated` 事件
4. **阅读 usePipelineConnection.ts**：理解为什么中间层只有 30 行但不可或缺
