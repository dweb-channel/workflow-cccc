/**
 * 验证类型定义
 *
 * 与后端 WorkflowValidator 完全对齐
 * 基于 DESIGN_SUPPLEMENT.md 设计
 */

// ============================================================================
// 核心数据结构（与后端对齐）
// ============================================================================

export interface NodeDefinition {
  id: string;
  type: string;  // 后端类型: llm_agent, cccc_peer, conditional, script
  label: string;
  config: Record<string, any>;
}

export interface EdgeDefinition {
  source: string;
  target: string;
  label?: string;
}

export interface WorkflowDefinition {
  id: string;
  title: string;
  entry_point: string;
  nodes: NodeDefinition[];
  edges: EdgeDefinition[];
  status: WorkflowStatus;
  error_policy?: ErrorHandlingPolicy;
  retry_config?: RetryConfig;
}

export type WorkflowStatus = 'draft' | 'invalid_draft' | 'published' | 'archived';

export type ErrorHandlingPolicy = 'stop_on_error' | 'continue' | 'retry';

export interface RetryConfig {
  max_attempts: number;
  delay_seconds: number;
  backoff_multiplier: number;
}

// ============================================================================
// 验证结果（与后端 ValidationResult 一致）
// ============================================================================

export interface ValidationResult {
  valid: boolean;
  errors: ValidationError[];
  warnings: ValidationWarning[];
}

/**
 * 验证错误
 *
 * context 字段契约（与 browser-tester 对齐）：
 * - MISSING_FIELD_REFERENCE: { field, available_fields, upstream_node_ids }
 * - CIRCULAR_DEPENDENCY: { cycle_path }
 * - DANGLING_NODE: { connection_suggestions? }
 */
export interface ValidationError {
  code: ValidationErrorCode;
  message: string;
  severity: 'error';
  node_ids: string[];  // 永远是数组（即使单个节点）
  context?: ValidationErrorContext;
}

export interface ValidationWarning {
  code: ValidationWarningCode;
  message: string;
  severity: 'warning';
  node_ids: string[];
  context?: ValidationWarningContext;
}

// ============================================================================
// 错误代码枚举
// ============================================================================

export type ValidationErrorCode =
  | 'CIRCULAR_DEPENDENCY'
  | 'MISSING_FIELD_REFERENCE'
  | 'INVALID_ENTRY_POINT'
  | 'DANGLING_NODE'
  | 'INVALID_NODE_CONFIG'
  | 'MISSING_REQUIRED_FIELD';

export type ValidationWarningCode =
  | 'NO_OUTGOING_EDGE'
  | 'NO_INCOMING_EDGE'
  | 'UNUSED_OUTPUT_FIELD'
  | 'MISSING_OUTPUT_FIELD';

// ============================================================================
// Context 字段类型（零防御性检查保障）
// ============================================================================

/**
 * MISSING_FIELD_REFERENCE 错误的 context
 *
 * 保证：
 * - field: 非空字符串
 * - available_fields: 非空数组
 * - upstream_node_ids: 非空数组
 */
export interface MissingFieldReferenceContext {
  field: string;
  available_fields: string[];  // 保证非空
  upstream_node_ids: string[]; // 保证非空
}

/**
 * CIRCULAR_DEPENDENCY 错误的 context
 *
 * 保证：
 * - cycle_path: 至少 3 个节点（起点 → 中间 → 回到起点）
 */
export interface CircularDependencyContext {
  cycle_path: string[];  // 至少 3 个元素
}

/**
 * DANGLING_NODE 警告的 context
 *
 * connection_suggestions 是可选的，但如果存在则非空
 */
export interface DanglingNodeContext {
  connection_suggestions?: string[];  // 如果存在，保证非空
}

/**
 * INVALID_ENTRY_POINT 错误的 context
 */
export interface InvalidEntryPointContext {
  expected: string;
  available_nodes: string[];
}

/**
 * 统一的 context 类型（用于类型窄化）
 */
export type ValidationErrorContext =
  | MissingFieldReferenceContext
  | CircularDependencyContext
  | DanglingNodeContext
  | InvalidEntryPointContext;

export type ValidationWarningContext =
  | DanglingNodeContext
  | { unused_field: string }
  | { missing_output: string };

// ============================================================================
// 工具类型
// ============================================================================

/**
 * 节点图（用于算法）
 */
export interface NodeGraph {
  nodes: Map<string, NodeDefinition>;
  edges: Map<string, string[]>;  // source -> targets[]
  reverseEdges: Map<string, string[]>;  // target -> sources[]
  inDegree: Map<string, number>;
  outDegree: Map<string, number>;
}

/**
 * 字段追踪信息
 */
export interface FieldTracker {
  availableFields: Set<string>;  // 当前可用字段
  nodeOutputs: Map<string, string>;  // node_id -> output_field
}

// ============================================================================
// 类型保护函数（用于类型窄化）
// ============================================================================

export function isMissingFieldReferenceError(
  error: ValidationError
): error is ValidationError & { context: MissingFieldReferenceContext } {
  return error.code === 'MISSING_FIELD_REFERENCE' && !!error.context;
}

export function isCircularDependencyError(
  error: ValidationError
): error is ValidationError & { context: CircularDependencyContext } {
  return error.code === 'CIRCULAR_DEPENDENCY' && !!error.context;
}

export function isDanglingNodeWarning(
  warning: ValidationWarning
): warning is ValidationWarning & { context: DanglingNodeContext } {
  return warning.code === 'NO_OUTGOING_EDGE' && !!warning.context;
}

// ============================================================================
// 常量
// ============================================================================

/**
 * 初始可用字段（在任何节点执行前）
 */
export const INITIAL_FIELDS = new Set(['run_id', 'request']);

/**
 * 特殊节点 ID
 */
export const SPECIAL_NODES = {
  END: '__END__',
  START: '__START__'
} as const;

/**
 * 错误代码 → 用户友好标题
 */
export const ERROR_TITLES: Record<ValidationErrorCode, string> = {
  CIRCULAR_DEPENDENCY: '检测到环路',
  MISSING_FIELD_REFERENCE: '字段引用错误',
  INVALID_ENTRY_POINT: '无效入口点',
  DANGLING_NODE: '节点未连接',
  INVALID_NODE_CONFIG: '节点配置错误',
  MISSING_REQUIRED_FIELD: '缺少必填字段'
};

/**
 * 警告代码 → 用户友好标题
 */
export const WARNING_TITLES: Record<ValidationWarningCode, string> = {
  NO_OUTGOING_EDGE: '节点无出边',
  NO_INCOMING_EDGE: '节点无入边',
  UNUSED_OUTPUT_FIELD: '输出字段未使用',
  MISSING_OUTPUT_FIELD: '缺少输出字段'
};
