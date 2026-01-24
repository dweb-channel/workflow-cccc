# 变更：接口清单补充（分页/过滤、RunRequest、时间/状态枚举）

## 目的
将风险点沉淀为 OpenSpec 变更条目，明确接口的分页/过滤、运行请求体与字段标准化。

## 变更内容
1) 查询类接口增加分页与过滤：
- `/api/workflows` 与 `/api/workflows/{id}/logs` 增加 `page`、`pageSize`、`status`、`timeRange`。

2) 运行接口支持可选请求体 `RunRequest`：
- 支持 `parameters` 覆盖默认参数。
- 支持 `dryRun`、`priority`。
- 支持 `clientRequestId` 幂等。

3) 字段标准化：
- 时间字段统一 ISO8601（含时区）。
- `status` 使用枚举（`draft` | `running` | `success` | `failed` | `paused`）。

## 影响范围
- OpenSpec 文档：接口清单文字说明与字段建议。
- FastAPI 实现：请求解析与分页/过滤处理逻辑。
- UI：日志列表与运行状态展示。

## 待确认
- `timeRange` 具体格式（`start,end` 或 ISO8601 区间）。
- `status` 枚举是否需要扩展（`queued`、`canceled` 等）。

