# T169: 前端工程实战 — React / Next.js / Tailwind

> **作者**: code-simplifier (前端专家)
> **目标读者**: 想成为高级 AI 应用前端开发工程师的你
> **前置要求**: 基本了解 HTML/CSS/JavaScript，了解 React 基础概念
> **与 T166 的关系**: T166 讲的是 SSE Hook 内部实现（数据流），本文讲的是工程架构模式（怎么组织代码）

---

## 目录

1. [S1: Next.js App Router 实战](#s1-nextjs-app-router-实战)
2. [S2: React 组件设计模式](#s2-react-组件设计模式)
3. [S3: Tailwind CSS 实战 + 深色模式](#s3-tailwind-css-实战--深色模式)

---

## S1: Next.js App Router 实战

### 1.1 项目技术栈一览

本项目前端的核心依赖：

| 库 | 版本 | 用途 |
|---|---|---|
| Next.js | 14.x | App Router + SSR 框架 |
| React | 18.x | UI 库 |
| TypeScript | 5.x | 类型安全 |
| Tailwind CSS | 3.x | 原子化 CSS |
| @xyflow/react | 12.x | 工作流画布（ReactFlow） |
| @radix-ui/* | 各组件 | 无样式可访问组件（shadcn/ui 基础） |
| class-variance-authority | 0.7.x | 组件变体管理 |
| lucide-react | 0.469.x | 图标库 |

**关键洞察**: 本项目不用 Redux、Zustand 等全局状态管理库。每个页面通过自定义 Hook 管理自己的状态，页面间不共享运行时状态。这是 Next.js App Router 推荐的模式——**状态尽量下沉到使用它的组件**。

---

### 1.2 目录结构解析

```
frontend/
├── app/                          ← Next.js App Router 根目录
│   ├── layout.tsx                ← 根布局（全局 Sidebar + ThemeProvider + Toaster）
│   ├── page.tsx                  ← 工作流编辑器首页（"/" 路由）
│   ├── error.tsx                 ← 全局错误边界
│   ├── globals.css               ← 全局样式 + CSS 变量（主题）
│   ├── hooks/                    ← 首页专用 Hook（useWorkflowEditor 等）
│   ├── components/               ← 首页专用组件（WorkflowSidebar 等）
│   ├── batch-bugs/               ← 批量 Bug 修复页面（"/batch-bugs" 路由）
│   │   ├── page.tsx
│   │   ├── hooks/                ← 页面专用 Hook
│   │   ├── components/           ← 页面专用组件
│   │   └── types.ts              ← 页面专用类型
│   ├── design-to-code/           ← 设计转代码页面（"/design-to-code" 路由）
│   │   ├── page.tsx
│   │   ├── hooks/
│   │   ├── components/
│   │   ├── spec-browser/         ← SpecBrowser 子模块（10 个文件）
│   │   └── types.ts
│   ├── canvas/                   ← 画布页面
│   └── test-harness/             ← 测试工具页面
│
├── components/                   ← 跨页面共享组件
│   ├── ui/                       ← shadcn/ui 组件（15 个）
│   ├── sidebar/                  ← 全局侧边栏
│   ├── theme-provider.tsx        ← 主题切换 Context
│   ├── workflow-editor/          ← 工作流编辑器组件
│   └── validation/               ← 图验证组件
│
├── lib/                          ← 共享工具库
│   ├── api.ts                    ← 后端 API 调用封装
│   ├── utils.ts                  ← 工具函数（cn）
│   ├── useSSEStream.ts           ← SSE 底层 Hook（详见 T166）
│   ├── usePipelineConnection.ts  ← Pipeline 连接管理（详见 T166）
│   ├── validation/               ← 图验证逻辑
│   └── types/                    ← 共享类型定义
│
├── tailwind.config.ts            ← Tailwind 配置
└── package.json                  ← ESM 模式（"type": "module"）
```

**核心设计原则 — 共置（Colocation）**:

每个路由页面的 hooks、components、types 都放在该路由目录下，而不是全部塞进顶层 `components/` 或 `hooks/`。只有**跨页面共享**的才提升到顶层。

```
✅ app/batch-bugs/hooks/useBatchJob.ts     ← 只在 batch-bugs 页面用
✅ app/batch-bugs/components/ActivityFeed.tsx ← 只在 batch-bugs 页面用
✅ lib/useSSEStream.ts                      ← 两个页面都用，提升到 lib/
✅ components/ui/button.tsx                  ← 全局共享 UI 组件

❌ hooks/useBatchJob.ts                      ← 不要放顶层，会误导其他页面开发者
❌ components/ActivityFeed.tsx                ← 不要放顶层，它只属于 batch-bugs
```

---

### 1.3 layout.tsx — 根布局的三重职责

```typescript
// frontend/app/layout.tsx
export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="zh-CN" suppressHydrationWarning>
      <head>
        {/* 职责 1: FOUC 防闪烁脚本 — 在 React hydrate 之前就设置 dark class */}
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
      </head>
      <body className="min-h-screen bg-background text-foreground">
        {/* 职责 2: 全局 Provider 嵌套 */}
        <ThemeProvider>
          <div className="flex h-screen overflow-hidden">
            {/* 职责 3: 跨页面共享的 Sidebar */}
            <Sidebar />
            <main className="flex-1 overflow-hidden">
              {children}       {/* ← 各个路由页面在这里渲染 */}
            </main>
          </div>
          <Toaster />          {/* 全局 Toast 通知 */}
        </ThemeProvider>
      </body>
    </html>
  );
}
```

**三个关键知识点**:

1. **`suppressHydrationWarning`**: 因为 `<head>` 里的内联脚本会在服务端和客户端产生不同的 DOM（dark class），这个属性告诉 React 不要报 hydration 警告。
2. **Sidebar 在 layout 层**: 这意味着切换路由时 Sidebar 不会重新渲染。用户在 `/batch-bugs` 和 `/design-to-code` 之间切换，Sidebar 状态保持稳定。
3. **`overflow-hidden` 组合**: `h-screen` + `overflow-hidden` 创建了一个固定视口，内部滚动由各页面自己管理。这防止了 Sidebar 和 main 同时滚动的混乱体验。

---

### 1.4 路由组织 — 三大页面对比

| 路由 | 页面 | 复杂度 | 特点 |
|---|---|---|---|
| `/` | 工作流编辑器 | 高 | ReactFlow 画布 + CRUD + 模板 + 执行 |
| `/batch-bugs` | 批量 Bug 修复 | 高 | 双 Tab + SSE + ActivityFeed + 表单 |
| `/design-to-code` | 设计转代码 | 高 | Figma 扫描 + SpecBrowser + SSE |

每个页面都遵循相同的组织模式：

```typescript
// 通用页面结构模式
"use client";                           // ← 全部是客户端组件
import { Suspense } from "react";

export default function SomePage() {
  return (
    <Suspense fallback={<Loading />}>   // ← Suspense 包裹
      <SomePageContent />               // ← 真正的页面逻辑
    </Suspense>
  );
}

function SomePageContent() {
  const searchParams = useSearchParams(); // ← 需要 Suspense 边界
  // ... 页面逻辑
}
```

**为什么要 Suspense?** `useSearchParams()` 在 Next.js App Router 中会触发客户端悬挂（suspend）。不包裹 Suspense 会导致整个页面回退到服务端渲染，产生警告。

---

### 1.5 Server Component vs Client Component

在本项目中，**所有页面组件都是 Client Component**（`"use client"`）。这是因为：

- 工作流编辑器需要 `@xyflow/react`（DOM 交互密集）
- 批量修复页需要 SSE 实时更新（浏览器 EventSource API）
- 设计转代码需要 Figma 扫描交互 + SSE

**唯一的 Server Component 是 `layout.tsx`**——它导出 `metadata`（标题、描述），只有 Server Component 才能导出静态 metadata。

```typescript
// layout.tsx — Server Component（没有 "use client"）
export const metadata = {            // ← 只有 Server Component 能导出
  title: "工作流操作台",
  description: "工作流操作页面"
};
```

**实战建议**: 对于 AI 应用前端，大部分页面都是交互密集型的，Server Component 的优势（减少 JS 体积、服务端数据获取）不明显。不要为了用 Server Component 而强行拆分，保持简单。

---

### 1.6 error.tsx — 错误边界

Next.js App Router 的 `error.tsx` 自动成为该路由段的错误边界：

```typescript
// app/error.tsx — 全局错误边界
"use client";  // ← 错误边界必须是 Client Component

export default function GlobalError({
  error,
  reset,       // ← Next.js 注入的重试函数
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error("Unhandled error:", error);
  }, [error]);

  return (
    <div className="flex h-full flex-col items-center justify-center gap-4 p-8">
      <Button onClick={reset} variant="outline" size="sm">
        Try again
      </Button>
    </div>
  );
}
```

注意 `batch-bugs/error.tsx` 和 `design-to-code/error.tsx` 也各有自己的错误边界，遵循**就近原则**——最近的 error.tsx 先捕获。

---

## S2: React 组件设计模式

### 2.1 shadcn/ui 组件库集成

本项目使用 [shadcn/ui](https://ui.shadcn.com/) 的模式，但不是直接装 `shadcn` CLI，而是手动维护组件文件。核心思路：**组件代码在你的仓库里，你完全拥有它**。

当前 15 个 UI 组件：

```
components/ui/
├── alert-dialog.tsx   ← 确认对话框（基于 @radix-ui/react-alert-dialog）
├── badge.tsx          ← 标签
├── button.tsx         ← 按钮（5 个变体：default/secondary/ghost/destructive/outline）
├── card.tsx           ← 卡片容器
├── checkbox.tsx       ← 复选框（原生 HTML input，非 Radix）
├── dialog.tsx         ← 通用对话框
├── input.tsx          ← 输入框
├── label.tsx          ← 表单标签
├── select.tsx         ← 下拉选择
├── switch.tsx         ← 开关
├── table.tsx          ← 表格
├── tabs.tsx           ← Tab 切换
├── textarea.tsx       ← 多行输入
├── toast.tsx          ← Toast 通知
└── toaster.tsx        ← Toast 容器
```

#### Button 组件深入解读

```typescript
// components/ui/button.tsx
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

// cva() — 定义带变体的 CSS 类
const buttonVariants = cva(
  // 基础类：所有按钮都有这些样式
  "inline-flex items-center justify-center gap-2 rounded-md text-sm font-medium transition-colors ...",
  {
    variants: {
      variant: {
        default:     "bg-primary text-primary-foreground hover:bg-primary/90",
        secondary:   "bg-secondary text-secondary-foreground border border-border ...",
        ghost:       "bg-transparent text-muted-foreground hover:bg-muted/50 ...",
        destructive: "bg-destructive text-destructive-foreground ...",
        outline:     "border border-border bg-transparent ...",
      },
      size: {
        default: "h-9 px-4",
        sm:      "h-8 px-3",
        lg:      "h-10 px-6",
      },
    },
    defaultVariants: { variant: "default", size: "default" },
  }
);

// forwardRef — 允许父组件获取底层 DOM 引用
const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, ...props }, ref) => (
    <button
      ref={ref}
      className={cn(buttonVariants({ variant, size, className }))}  // ← cn() 合并类名
      {...props}
    />
  )
);
```

**三个关键工具链**:

1. **`class-variance-authority` (cva)**: 类型安全地定义组件变体。比手动写 `if/else` 拼接类名更可维护。
2. **`clsx`**: 条件性合并 CSS 类名。`clsx("foo", false && "bar", "baz")` → `"foo baz"`。
3. **`tailwind-merge` (twMerge)**: 智能合并 Tailwind 类。`twMerge("px-4 px-6")` → `"px-6"`（后者覆盖前者）。

`cn()` 工具函数把两者组合：

```typescript
// lib/utils.ts — 整个项目最常用的函数
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}
```

---

### 2.2 复合组件模式 — Sidebar 实战

Sidebar 展示了一个常见的复合组件模式：

```typescript
// components/sidebar/Sidebar.tsx
function NavItem({ href, icon: Icon, label, isActive }: NavItemProps) {
  return (
    <Link
      href={href}
      className={`... ${
        isActive
          ? "bg-primary/10 text-primary border-l-2 border-primary"     // 激活态
          : "text-sidebar-foreground hover:bg-muted border-l-2 border-transparent"  // 默认态
      }`}
    >
      <Icon className="h-4 w-4" />
      <span>{label}</span>
    </Link>
  );
}

export function Sidebar() {
  const pathname = usePathname();  // ← Next.js Hook: 获取当前路由

  return (
    <aside className="flex w-[220px] shrink-0 flex-col border-r border-border bg-sidebar">
      <div className="px-4 py-4">
        <h1 className="text-lg font-bold text-foreground">工作流平台</h1>
      </div>

      <nav className="flex-1 space-y-1 px-3">
        {navItems.map((item) => {
          // 路由匹配逻辑 — 支持嵌套路由
          const isActive =
            item.path === "/"
              ? pathname === "/" || pathname.startsWith("/workflow")
              : pathname === item.path || pathname.startsWith(item.path + "/");
          return <NavItem key={item.path} {...item} isActive={isActive} />;
        })}
      </nav>

      <div className="border-t border-border px-3 py-3">
        <ThemeToggle />
      </div>
    </aside>
  );
}
```

**设计要点**:
- **数据驱动导航**: `navItems` 数组定义导航项，组件只负责渲染。后续可以改为 API 驱动（已有 TODO 标记）。
- **路由匹配**: `usePathname()` + `startsWith()` 支持子路由匹配。`/batch-bugs/123` 也会高亮 "批量 Bug 修复"。
- **固定宽度**: `w-[220px] shrink-0` — Sidebar 不参与 flex 伸缩，保持固定宽度。

---

### 2.3 页面组件拆分 — 从 1000 行到模块化

这是本教程最重要的实战案例。在 M27 之前，`batch-bugs/page.tsx` 超过 1000 行，把表单、SSE 处理、活动流、历史记录全写在一个文件里。

#### 为什么必须拆分？

| 问题 | 影响 |
|---|---|
| **代码审查效率低** | 改一个 Bug 也要 review 1000 行文件的 diff |
| **合并冲突** | 多人改同一个文件，冲突概率极高 |
| **测试困难** | 无法单独测试某个功能模块 |
| **认知负担** | 新人打开文件就懵了——"这个 useState 是给谁用的？" |
| **状态泄漏** | 所有状态都在一个作用域，容易产生意外依赖 |

#### 拆分策略 — 两个维度

**维度 1: 按功能域抽取 Hook（逻辑拆分）**

```
page.tsx（拆分前）                    page.tsx（拆分后）
┌───────────────────────┐            ┌───────────────────────┐
│ useState x 20+        │            │ const crud = useWorkflowCRUD({...});
│ useEffect x 8+        │    →       │ const editor = useWorkflowEditor({...});
│ handleXxx x 15+       │            │ const execution = useWorkflowExecution({...});
│ 复杂 JSX x 500+ 行   │            │ // JSX 只负责布局编排
└───────────────────────┘            └───────────────────────┘
```

以工作流编辑器首页为例，拆分为 3 个 Hook：

```typescript
// 首页 page.tsx — 拆分后只有组合逻辑
function WorkflowPage() {
  const [editorMode, setEditorMode] = useState<EditorMode>("view");
  const [graphChanged, setGraphChanged] = useState(false);
  const [nodes, setNodes, onNodesChange] = useNodesState<FlowNode>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<FlowEdge>([]);

  // Hook 1: CRUD — 工作流列表加载、创建、删除、重命名
  const crud = useWorkflowCRUD({ setNodes, setEdges, editorMode, setGraphChanged, toast });

  // Hook 2: Editor — 节点拖放、连线、图保存、模板应用
  const editor = useWorkflowEditor({
    nodes, setNodes, edges, setEdges, reactFlowInstance,
    workflow: crud.workflow, editorMode, setEditorMode,
    graphChanged, setGraphChanged, toast,
  });

  // Hook 3: Execution — 运行工作流、SSE 监听、状态更新
  const execution = useWorkflowExecution({
    workflow: crud.workflow, setNodes, setEdges,
    loadWorkflow: crud.loadWorkflow, setEditorMode,
  });

  // JSX 只做布局编排，不含任何业务逻辑
  return (
    <div className="flex h-full overflow-hidden">
      <WorkflowSidebar {...crud} onApplyTemplate={editor.handleApplyTemplate} />
      <div className="flex flex-1 flex-col gap-4 overflow-hidden px-6 py-6">
        {/* ... */}
      </div>
    </div>
  );
}
```

**Hook 拆分原则**:
1. **一个 Hook 一个功能域**: `useWorkflowCRUD` 只管增删改查，`useWorkflowEditor` 只管画布编辑。
2. **Hook 之间通过参数通信**: `execution` 需要 `crud.workflow`，通过参数传入而非全局状态。
3. **状态提升（Lifting State Up）**: `editorMode` 和 `graphChanged` 是跨 Hook 共享的，提升到 page.tsx 层。

**维度 2: 按 UI 区域抽取组件（视图拆分）**

```
batch-bugs/page.tsx
  ├── components/BugInput.tsx         ← 左侧 Bug 输入表单
  ├── components/ConfigOptions.tsx    ← 配置选项区域
  ├── components/DirectoryPicker.tsx  ← 目录选择器
  ├── components/OverviewTab.tsx      ← 总览 Tab
  ├── components/HistoryCard.tsx      ← 历史记录卡片
  ├── components/ActivityFeed.tsx     ← 活动流（对话式执行视图）
  ├── components/PipelineBar.tsx      ← Pipeline 进度条
  ├── components/MetricsTab.tsx       ← 指标 Tab
  ├── components/WorkspaceTabs.tsx    ← Workspace Tab 切换
  ├── components/WorkspaceDialog.tsx  ← Workspace 新建对话框
  └── components/WorkspacePanel.tsx   ← Workspace 面板
```

**拆分粒度判断**:
- 如果一段 JSX 超过 50 行，考虑抽组件
- 如果一段 JSX 有自己的 useState/useEffect，必须抽组件
- 如果一段 JSX 在条件渲染中（如 Tab 切换），适合抽组件

---

### 2.4 useReducer vs useState — 何时升级

大部分场景用 `useState` 足够。但当状态转换有**明确的状态机语义**时，`useReducer` 更清晰：

```typescript
// design-to-code/page.tsx — Figma 扫描状态机
type ScanState = {
  step: "idle" | "scanning" | "selecting";
  result: FigmaScanResponse | null;
  error: string | null;
};

type ScanAction =
  | { type: "START_SCAN" }
  | { type: "SCAN_SUCCESS"; result: FigmaScanResponse }
  | { type: "SCAN_ERROR"; error: string }
  | { type: "RESET" };

function scanReducer(_state: ScanState, action: ScanAction): ScanState {
  switch (action.type) {
    case "START_SCAN":
      return { step: "scanning", result: null, error: null };
    case "SCAN_SUCCESS":
      return { step: "selecting", result: action.result, error: null };
    case "SCAN_ERROR":
      return { step: "idle", result: null, error: action.error };
    case "RESET":
      return SCAN_INITIAL;
  }
}

// 使用
const [scan, dispatchScan] = useReducer(scanReducer, SCAN_INITIAL);
// dispatchScan({ type: "START_SCAN" });
```

**何时用 useReducer**:
- 状态之间有**互斥关系**（scanning 时不能有 error，selecting 时必须有 result）
- 状态转换可以画出**状态图**
- 多个 useState 总是需要一起更新（避免中间不一致状态）

**何时用 useState**:
- 独立的布尔/字符串/数字值
- 没有复杂的状态转换规则

---

### 2.5 TypeScript 实战模式

#### Discriminated Union — 类型安全的事件处理

```typescript
// design-to-code/page.tsx（组件内局部定义，非独立 types 文件）
type ScanAction =
  | { type: "START_SCAN" }                               // 无额外数据
  | { type: "SCAN_SUCCESS"; result: FigmaScanResponse }  // 带 result
  | { type: "SCAN_ERROR"; error: string }                // 带 error
  | { type: "RESET" };                                   // 无额外数据
```

TypeScript 会在 `switch (action.type)` 中自动收窄类型：`case "SCAN_SUCCESS"` 分支里，`action.result` 的类型是 `FigmaScanResponse`，不需要手动断言。

#### 泛型 Hook — 类型安全的复用

```typescript
// lib/useSSEStream.ts（T166 详细讲解了内部实现，这里只看类型设计）
export interface UseSSEStreamOptions {
  url: string | null | undefined;     // null = 不连接（门控）
  handlers: Record<string, (data: unknown) => void>;
  terminalEvents?: string[];
  // ...
}
```

`url` 接受 `null | undefined` 是一个**门控模式**：Hook 始终被调用（React 要求 Hook 调用顺序不变），但通过 `url === null` 表示"不需要连接"。

#### Record 类型 — 映射表

```typescript
// page.tsx — 状态映射表
const STATUS_MAP: Record<string, { label: string; color: string }> = {
  draft:     { label: "草稿",   color: "bg-muted-foreground" },
  published: { label: "已发布", color: "bg-blue-500" },
  running:   { label: "运行中", color: "bg-emerald-500" },
  success:   { label: "成功",   color: "bg-green-500" },
  failed:    { label: "失败",   color: "bg-red-500" },
};
```

---

### 2.6 API 调用封装

所有后端 API 调用集中在 `lib/api.ts`：

```typescript
// lib/api.ts
const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

// 类型定义与 API 函数在同一文件 — 保证 API 契约和类型同步
export interface V2WorkflowResponse {
  id: string;
  name: string;
  status: string;
  version: string;
  graph_definition: { ... } | null;
  created_at: string;
  updated_at: string;
}

export async function listWorkflows(): Promise<V2PagedWorkflowsResponse> {
  const res = await fetch(`${API_BASE}/api/v2/workflows?page_size=20`);
  if (!res.ok) throw new Error(`Failed to fetch workflows: ${res.status}`);
  return res.json();
}
```

**设计原则**:
- **环境变量驱动**: `NEXT_PUBLIC_API_URL` 允许 Docker 部署时指向不同后端。`NEXT_PUBLIC_` 前缀是 Next.js 要求——只有这个前缀的环境变量才会打包到客户端 bundle。
- **类型与函数同置**: TypeScript 接口和 API 函数放在一起，改 API 时不会忘改类型。
- **原生 fetch**: 不用 axios。Next.js 对原生 `fetch` 有缓存优化，且减少一个依赖。

---

## S3: Tailwind CSS 实战 + 深色模式

### 3.1 Tailwind 配置剖析

```typescript
// tailwind.config.ts
const config: Config = {
  darkMode: ["class"],               // ← 使用 class 策略（.dark 类）
  content: [                          // ← 扫描范围
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}"
  ],
  theme: {
    extend: {
      colors: {
        // 全部颜色通过 CSS 变量间接引用
        background:       "rgb(var(--color-background) / <alpha-value>)",
        foreground:       "rgb(var(--color-foreground) / <alpha-value>)",
        primary:          "rgb(var(--color-primary) / <alpha-value>)",
        "primary-foreground": "rgb(var(--color-primary-foreground) / <alpha-value>)",
        // ... 共 16 个语义化颜色
      },
      borderRadius: {
        lg: "0.75rem",
        md: "0.5rem",
        sm: "0.25rem",
      },
    },
  },
};
```

**关键设计**:

1. **`darkMode: ["class"]`**: 通过 `<html class="dark">` 切换主题，而不是 `@media (prefers-color-scheme: dark)`。这允许用户手动选择，不受系统设置约束。

2. **CSS 变量间接引用**: `bg-primary` 不是直接映射到 `#0891B2`，而是映射到 `rgb(var(--color-primary))`。切换主题时只需改变 CSS 变量值，所有使用 `bg-primary` 的地方自动更新。

3. **`<alpha-value>` 透明度支持**: Tailwind 的 `bg-primary/90` 会编译为 `rgb(var(--color-primary) / 0.9)`，CSS 变量存储的是 RGB 数值（不带 `rgb()`），这样才能支持 `/90` 语法。

---

### 3.2 CSS 变量体系 — 主题的核心

```css
/* globals.css */

/* 浅色主题（默认） */
:root {
  --color-background: 248 250 252;       /* slate-50 */
  --color-foreground: 15 23 42;          /* slate-900 */
  --color-primary: 8 145 178;           /* cyan-600 */
  --color-card: 255 255 255;            /* white */
  --color-border: 226 232 240;          /* slate-200 */
  --color-muted-foreground: 100 116 139; /* slate-500 */
  /* ... */
}

/* 深色主题 */
.dark {
  --color-background: 15 23 42;          /* slate-900 → 深蓝背景 */
  --color-foreground: 248 250 252;       /* slate-50 → 浅色文字 */
  --color-primary: 34 211 238;          /* cyan-400 → 更亮的主色 */
  --color-card: 30 41 59;              /* slate-800 → 深色卡片 */
  --color-border: 51 65 85;            /* slate-700 → 深色边框 */
  --color-muted-foreground: 148 163 184; /* slate-400 → 浅色辅助文字 */
  /* ... */
}
```

**16 个语义化颜色的命名逻辑**:

| 颜色 | 用途 |
|---|---|
| `background` / `foreground` | 页面底色 / 主文字 |
| `card` / `card-foreground` | 卡片底色 / 卡片文字 |
| `muted` / `muted-foreground` | 弱化区域底色 / 弱化文字 |
| `primary` / `primary-foreground` | 主操作色（按钮等） / 主操作色上的文字 |
| `secondary` / `secondary-foreground` | 次要操作色 / 次要操作色上的文字 |
| `accent` / `accent-foreground` | 强调色 / 强调色上的文字 |
| `border` / `input` / `ring` | 边框 / 输入框边框 / 聚焦环 |
| `sidebar` / `sidebar-foreground` | 侧边栏底色 / 侧边栏文字 |
| `destructive` / `destructive-foreground` | 危险操作色 / 危险操作文字 |

**命名规则**: 每个背景色都有对应的 `-foreground`，确保文字在该背景上可读。写代码时：

```tsx
// ✅ 正确 — 背景和文字成对使用
<div className="bg-card text-card-foreground">卡片内容</div>
<button className="bg-primary text-primary-foreground">提交</button>

// ❌ 错误 — 背景和文字不配对，深色模式下可能看不见
<div className="bg-card text-foreground">可能不可读</div>
```

---

### 3.3 ThemeProvider 实现

```typescript
// components/theme-provider.tsx
export function ThemeProvider({ children }: { children: ReactNode }) {
  const [theme, setTheme] = useState<Theme>("light");
  const [mounted, setMounted] = useState(false);

  // 1. 挂载时从 localStorage 读取
  useEffect(() => {
    const stored = localStorage.getItem("theme") as Theme | null;
    if (stored === "dark" || stored === "light") {
      setTheme(stored);
    }
    setMounted(true);
  }, []);

  // 2. 主题变化时同步 DOM + localStorage
  useEffect(() => {
    if (!mounted) return;
    const root = document.documentElement;
    if (theme === "dark") {
      root.classList.add("dark");
    } else {
      root.classList.remove("dark");
    }
    localStorage.setItem("theme", theme);
  }, [theme, mounted]);

  // 3. 防闪烁：mounted 前不渲染 Provider
  if (!mounted) {
    return <>{children}</>;  // ← 子组件正常渲染，但 useTheme() 拿到默认值
  }

  return (
    <ThemeContext.Provider value={{ theme, toggleTheme }}>
      {children}
    </ThemeContext.Provider>
  );
}
```

**防闪烁（FOUC）双重保障**:

1. **layout.tsx 内联脚本**: 在 React hydrate 之前就设置 `.dark` class，避免页面先白后黑的闪烁。
2. **ThemeProvider mounted 守卫**: 确保 `localStorage` 读取完成前不会触发错误的主题切换。

---

### 3.4 Tailwind 常用模式速查

从项目中提炼的高频使用模式：

#### Flex 布局

```tsx
// 水平排列，居中对齐，间距
<div className="flex items-center gap-3">

// 垂直排列，填满高度
<div className="flex flex-col flex-1">

// 固定宽度 + 不参与收缩
<aside className="w-[220px] shrink-0">
```

#### 溢出控制

```tsx
// 整体不滚动，内部滚动
<div className="h-screen overflow-hidden">        {/* 外层固定 */}
  <div className="flex-1 overflow-y-auto">          {/* 内层可滚动 */}
```

#### 条件样式

```tsx
// 三元表达式 — 两态切换
className={editorMode === "edit" ? "bg-background/50" : "bg-background"}

// 模板字符串 — 动态拼接
className={`border-l-2 ${isActive ? "border-primary text-primary" : "border-transparent"}`}

// cn() — 多条件组合（推荐）
className={cn(
  "rounded-md px-3 py-2 text-sm",
  isActive && "bg-primary/10 text-primary",
  disabled && "opacity-50 pointer-events-none"
)}
```

#### 透明度快捷语法

```tsx
// bg-primary/90 = 90% 不透明度
<button className="bg-primary hover:bg-primary/90">

// bg-muted/50 = 50% 不透明度
<div className="hover:bg-muted/50">
```

#### 间距系统

```tsx
// gap — flex/grid 子元素间距（推荐）
<div className="flex gap-4">

// space-y — 垂直方向相邻兄弟间距
<div className="space-y-2">

// p/px/py — 内边距
<div className="px-6 py-4">
```

---

### 3.5 真实踩坑案例

#### 踩坑 1: Tailwind 类名冲突

```tsx
// ❌ 两个 padding 冲突，结果不确定
<div className="px-4 px-6">

// ✅ 使用 cn() + twMerge 自动去重
<div className={cn("px-4", someCondition && "px-6")}>
// twMerge 会保留 px-6，删除 px-4
```

#### 踩坑 2: 动态类名不生效

```tsx
// ❌ 动态拼接 — Tailwind 无法扫描到这个类名
const color = "red";
<div className={`bg-${color}-500`}>   // "bg-red-500" 不在编译产物中！

// ✅ 预定义完整类名
const colorMap = { red: "bg-red-500", green: "bg-green-500" };
<div className={colorMap[color]}>
```

Tailwind 是**编译时**工具，它扫描源码中的类名字符串。动态拼接的类名在编译时不存在完整字符串，所以不会被包含在 CSS 产物中。

#### 踩坑 3: 深色模式下颜色不对

```tsx
// ❌ 硬编码颜色 — 深色模式下白色文字在白色背景上
<p className="text-gray-900">标题</p>

// ✅ 使用语义化颜色
<p className="text-foreground">标题</p>          // 浅色=深色文字，深色=浅色文字
<p className="text-muted-foreground">辅助</p>   // 自动适配
```

项目规则：**永远不要直接用 Tailwind 内置颜色（如 `text-gray-900`、`bg-white`），始终用语义化颜色（如 `text-foreground`、`bg-card`）**。这样只需要维护 `globals.css` 中的 CSS 变量，就能保证深色/浅色模式一致。

---

## 总结 — 前端工程核心原则

| 原则 | 在项目中的体现 |
|---|---|
| **共置原则** | 页面专用文件放在路由目录下，不堆在顶层 |
| **单一职责** | 一个 Hook 一个功能域，一个组件一个 UI 区域 |
| **状态下沉** | 不用全局状态管理，状态放在最近的使用处 |
| **语义化颜色** | 通过 CSS 变量间接引用，不硬编码颜色值 |
| **类型安全** | Discriminated Union + 泛型 Hook + Record 映射 |
| **渐进式复杂度** | useState → useReducer，只在需要时升级 |

---

## 延伸阅读

- [T166: 前端核心 Hook + SSE 模式走读](./t166-frontend-hooks-sse.md) — SSE 三层抽象的内部实现
- [T164: 项目架构全景](./t164-architecture-overview.md) — 后端架构 + 数据流
- [T167: Pipeline 实操指南](./t167-pipeline-guide.md) — 端到端跑通两条 Pipeline
- [Next.js App Router 文档](https://nextjs.org/docs/app) — 官方参考
- [shadcn/ui](https://ui.shadcn.com/) — UI 组件库参考
