/**
 * 主验证器 - validateWorkflowClient()
 *
 * 集成所有验证模块，提供统一的客户端工作流验证接口
 *
 * 与后端 WorkflowValidator 对齐，确保 SSOT 原则：
 * - 相同输入产生相同验证结果
 * - 错误/警告格式完全一致
 * - Context 字段契约保证
 *
 * Phase 1 TDD 实施
 * Author: code-simplifier
 * Date: 2026-01-31
 */

import type {
  WorkflowDefinition,
  ValidationResult,
  ValidationError,
  ValidationWarning
} from './types';
import { detectCircularDependency } from './circularDependency';
import { validateFieldReferences } from './fieldReference';
import { detectDanglingNodes } from './danglingNode';

/**
 * 验证工作流定义的完整性和正确性
 *
 * @param workflow - 工作流定义
 * @returns 验证结果，包含 valid 标志、错误列表、警告列表
 *
 * 验证流程：
 * 1. 环路依赖检测（CIRCULAR_DEPENDENCY）
 * 2. 字段引用验证（MISSING_FIELD_REFERENCE）
 * 3. 悬空节点检测（DANGLING_NODE, NO_INCOMING_EDGE, NO_OUTGOING_EDGE）
 *
 * 验证结果格式与 Fixture v1.0 的 expected_validation_result 完全对齐
 */
export function validateWorkflowClient(
  workflow: WorkflowDefinition
): ValidationResult {
  const errors: ValidationError[] = [];
  const warnings: ValidationWarning[] = [];

  // 1. 环路依赖检测（阻塞性错误）
  // 使用 DFS 算法检测图中的环路
  const circularErrors = detectCircularDependency(workflow);
  errors.push(...circularErrors);

  // 2. 字段引用验证（阻塞性错误）
  // 使用拓扑排序 + 字段追踪验证字段引用的正确性
  // 注意：如果有环路，拓扑排序会失败，fieldReference 会跳过验证
  const fieldErrors = validateFieldReferences(workflow);
  errors.push(...fieldErrors);

  // 3. 悬空节点检测（警告）
  // 检测无入边且非入口点的节点，以及无出边的节点
  const { errors: danglingErrors, warnings: danglingWarnings } =
    detectDanglingNodes(workflow);
  errors.push(...danglingErrors);
  warnings.push(...danglingWarnings);

  // 确定工作流是否有效
  // valid = true 表示没有阻塞性错误（可以有警告）
  const valid = errors.length === 0;

  return {
    valid,
    errors,
    warnings
  };
}

/**
 * 快速验证工作流是否有效（不返回详细错误信息）
 *
 * @param workflow - 工作流定义
 * @returns true 表示工作流有效（无阻塞性错误）
 *
 * 用途：
 * - 实时验证（编辑时快速检查）
 * - 保存前验证
 * - UI 状态徽章显示
 */
export function isWorkflowValid(workflow: WorkflowDefinition): boolean {
  const result = validateWorkflowClient(workflow);
  return result.valid;
}

/**
 * 获取验证结果摘要
 *
 * @param result - 验证结果
 * @returns 摘要对象，包含错误数、警告数、是否有效
 *
 * 用途：
 * - 显示验证状态徽章
 * - 生成验证报告摘要
 */
export function getValidationSummary(result: ValidationResult): {
  valid: boolean;
  errorCount: number;
  warningCount: number;
  hasCircularDependency: boolean;
  hasFieldErrors: boolean;
  hasDanglingNodes: boolean;
} {
  const errorCodes = new Set(result.errors.map(e => e.code));
  const warningCodes = new Set(result.warnings.map(w => w.code));

  return {
    valid: result.valid,
    errorCount: result.errors.length,
    warningCount: result.warnings.length,
    hasCircularDependency: errorCodes.has('CIRCULAR_DEPENDENCY'),
    hasFieldErrors: errorCodes.has('MISSING_FIELD_REFERENCE'),
    hasDanglingNodes:
      warningCodes.has('NO_INCOMING_EDGE') ||
      warningCodes.has('NO_OUTGOING_EDGE')
  };
}

/**
 * 按节点分组错误和警告
 *
 * @param result - 验证结果
 * @returns 节点 ID 到错误/警告列表的映射
 *
 * 用途：
 * - 在节点上显示错误徽章
 * - 定位到具体节点的问题
 * - 按节点高亮显示错误
 */
export function groupErrorsByNode(result: ValidationResult): Map<
  string,
  {
    errors: ValidationError[];
    warnings: ValidationWarning[];
  }
> {
  const nodeErrors = new Map<
    string,
    {
      errors: ValidationError[];
      warnings: ValidationWarning[];
    }
  >();

  // 初始化所有节点的错误/警告列表
  const initNodeErrors = (nodeId: string) => {
    if (!nodeErrors.has(nodeId)) {
      nodeErrors.set(nodeId, { errors: [], warnings: [] });
    }
  };

  // 收集错误
  for (const error of result.errors) {
    for (const nodeId of error.node_ids) {
      initNodeErrors(nodeId);
      nodeErrors.get(nodeId)!.errors.push(error);
    }
  }

  // 收集警告
  for (const warning of result.warnings) {
    for (const nodeId of warning.node_ids) {
      initNodeErrors(nodeId);
      nodeErrors.get(nodeId)!.warnings.push(warning);
    }
  }

  return nodeErrors;
}

/**
 * 获取特定类型的错误
 *
 * @param result - 验证结果
 * @param errorCode - 错误代码
 * @returns 指定类型的错误列表
 *
 * 用途：
 * - 筛选特定类型的错误
 * - 分类显示错误
 */
export function getErrorsByType(
  result: ValidationResult,
  errorCode: string
): ValidationError[] {
  return result.errors.filter(e => e.code === errorCode);
}

/**
 * 获取特定类型的警告
 *
 * @param result - 验证结果
 * @param warningCode - 警告代码
 * @returns 指定类型的警告列表
 *
 * 用途：
 * - 筛选特定类型的警告
 * - 分类显示警告
 */
export function getWarningsByType(
  result: ValidationResult,
  warningCode: string
): ValidationWarning[] {
  return result.warnings.filter(w => w.code === warningCode);
}
