# 工作流操作/编辑页 规格（OpenSpec）

## 1. 范围
- 仅本次“工作流操作/编辑页”与其后端接口。
- 不包含运行引擎实现细节、登录/权限。

## 2. 页面结构（UI）
- 顶部区域：标题、版本/更新时间、运行状态、主操作按钮（运行/保存草稿/发布）。
- 中间区域：流程画布（拖拽节点）与画布工具栏（放大/缩小/自动布局）。
- 右侧栏：运行参数（触发人、优先级、计划时间、通知开关）与节点配置（文本描述）。
- 底部区域：日志/历史/告警 Tabs + 日志表格。

## 3. 数据模型（最小字段）
### 3.1 工作流
- id: string
- name: string
- status: string
- version: string
- created_at: string
- updated_at: string

### 3.2 运行参数
- trigger: string
- priority: enum(low|normal|high)
- schedule: string
- notifyBot: boolean

### 3.3 节点配置
- nodeConfig: string

### 3.4 日志
- runId: string
- time: string
- level: string
- message: string
- source: string

### 3.5 运行记录
- id: string
- workflowId: string
- status: string
- started_at: string
- ended_at: string?
- triggered_by: string

## 4. 接口清单（最小）
- 获取工作流列表
- 获取工作流详情
- 获取运行记录列表
- 获取工作流运行日志
- 运行工作流
- 保存参数/配置

## 4.1 接口文字说明（请求/响应字段）
### 获取工作流列表
- 方法：GET
- 路径：`/api/workflows`
- Query（建议）：`page`、`pageSize`、`status`、`timeRange`
- 响应：`WorkflowSummary[]`

### 获取工作流详情
- 方法：GET
- 路径：`/api/workflows/{id}`
- 响应：`WorkflowDetail`
- 错误：`404` -> `Error`

### 保存参数/配置
- 方法：POST
- 路径：`/api/workflows/{id}/save`
- 请求体：`SaveRequest`
  - parameters: `WorkflowParameters`（必填）
  - nodeConfig: object 或 string（建议 object）
  - clientRequestId: string（可选，幂等）
- 响应：`SaveResponse`
- 错误：`404` -> `Error`

### 运行工作流
- 方法：POST
- 路径：`/api/workflows/{id}/run`
- 请求体（可选）：`RunRequest`
  - request: string（可选，用于传入触发说明/需求文本）
  - parameters: `WorkflowParameters`（可选，覆盖默认）
  - clientRequestId: string（可选，幂等）
- 响应：`RunResponse`（包含 runId、status）
- 错误：`404` -> `Error`

### 获取工作流运行日志
- 方法：GET
- 路径：`/api/workflows/{id}/logs`
- Query（建议）：`page`、`pageSize`、`status`、`timeRange`
- 响应：`WorkflowLog[]`

### 获取运行记录列表
- 方法：GET
- 路径：`/api/workflows/{id}/runs`
- Query（建议）：`page`、`pageSize`、`status`、`timeRange`
- 响应：`RunRecord[]`

## 4.2 字段建议（枚举/时间）
- 时间字段统一 ISO8601（含时区）
- status 建议枚举：`draft` | `running` | `success` | `failed` | `paused`
- WorkflowParameters 可补：`env`、`retry`、`timeout`

## 5. Workflow 集成
- 后端使用 FastAPI，并通过 Temporal client 直接触发现有 `BusinessWorkflow`。
- 运行接口会把 `request` 透传给 workflow。
- Temporal 配置字段说明：`temporalNamespace`、`taskQueue`、`workflowId`、`runId`（用于定位与追踪运行实例）。

## 6. 待确认
- 是否新增接口（节点列表、画布保存、暂停/恢复、回滚）？
- 日志字段是否扩展（级别、耗时、traceId 等）？
- 保存是否区分草稿/发布？
