/**
 * 字段引用验证模块
 *
 * 算法：拓扑排序 + 字段追踪
 * 与后端 WorkflowValidator._validate_field_references() 完全对齐
 */

import type {
  WorkflowDefinition,
  ValidationError,
  MissingFieldReferenceContext,
  FieldTracker,
  NodeGraph
} from './types';
import { INITIAL_FIELDS } from './types';
import {
  topologicalSort,
  buildNodeGraph,
  getNodeInputFields,
  getNodeOutputField,
  getDirectUpstreamNodes
} from './utils';

/**
 * 验证字段引用的正确性
 *
 * @param workflow - 工作流定义
 * @returns 字段引用错误列表
 *
 * 算法流程：
 * 1. 对工作流进行拓扑排序（必须无环路）
 * 2. 按照拓扑顺序遍历节点，模拟执行
 * 3. 维护当前可用字段集合（从 INITIAL_FIELDS 开始）
 * 4. 对每个节点：
 *    a. 提取所需输入字段（input_fields + prompt_template 引用）
 *    b. 检查字段是否在可用字段集合中
 *    c. 如果缺失 → 生成错误（包含 available_fields context）
 *    d. 将节点的输出字段添加到可用字段集合
 */
export function validateFieldReferences(
  workflow: WorkflowDefinition
): ValidationError[] {
  const errors: ValidationError[] = [];

  // 1. 拓扑排序
  const sortedNodeIds = topologicalSort(workflow);
  if (sortedNodeIds === null) {
    // 有环路，无法进行字段分析（环路错误应该在 circularDependency.ts 中报告）
    return [];
  }

  const graph = buildNodeGraph(workflow);
  const tracker: FieldTracker = {
    availableFields: new Set(INITIAL_FIELDS),
    nodeOutputs: new Map()
  };

  // 2. 按拓扑顺序验证每个节点
  for (const nodeId of sortedNodeIds) {
    const node = graph.nodes.get(nodeId);
    if (!node) continue;

    // 提取节点需要的输入字段
    const requiredFields = getNodeInputFields(node);

    // 检查字段是否可用
    for (const field of requiredFields) {
      if (!tracker.availableFields.has(field)) {
        // 字段不可用 → 生成错误
        const upstreamNodes = getDirectUpstreamNodes(nodeId, graph);

        errors.push({
          code: 'MISSING_FIELD_REFERENCE',
          message: `节点 '${node.label}' 引用字段 '${field}'，但该字段在前置节点中未定义。可用字段: ${Array.from(
            tracker.availableFields
          )
            .sort()
            .join(', ')}`,
          severity: 'error',
          node_ids: [nodeId],
          context: {
            field,
            available_fields: Array.from(tracker.availableFields).sort(),
            upstream_node_ids: upstreamNodes.length > 0 ? upstreamNodes : []
          } satisfies MissingFieldReferenceContext
        });
      }
    }

    // 添加节点的输出字段到可用字段集合
    const outputField = getNodeOutputField(node);
    if (outputField) {
      tracker.availableFields.add(outputField);
      tracker.nodeOutputs.set(nodeId, outputField);
    }
  }

  return errors;
}

/**
 * 获取节点在执行时可用的字段列表
 *
 * 用于 UI 的字段自动补全功能
 *
 * @param workflow - 工作流定义
 * @param nodeId - 目标节点 ID
 * @returns 可用字段列表
 *
 * 实现：模拟执行到目标节点的前一步，返回累积的可用字段
 */
export function getAvailableFieldsForNode(
  workflow: WorkflowDefinition,
  nodeId: string
): string[] {
  // 拓扑排序
  const sortedNodeIds = topologicalSort(workflow);
  if (sortedNodeIds === null) {
    return Array.from(INITIAL_FIELDS);
  }

  const graph = buildNodeGraph(workflow);
  const availableFields = new Set(INITIAL_FIELDS);

  // 模拟执行到目标节点之前
  for (const currentNodeId of sortedNodeIds) {
    if (currentNodeId === nodeId) {
      // 到达目标节点，返回当前可用字段
      break;
    }

    const node = graph.nodes.get(currentNodeId);
    if (!node) continue;

    const outputField = getNodeOutputField(node);
    if (outputField) {
      availableFields.add(outputField);
    }
  }

  return Array.from(availableFields).sort();
}

/**
 * 检测未使用的输出字段（警告）
 *
 * 如果一个节点定义了 output_field，但该字段在后续节点中从未被引用，
 * 则可能是配置错误或冗余配置
 *
 * @param workflow - 工作流定义
 * @returns 警告列表
 */
export function detectUnusedOutputFields(
  workflow: WorkflowDefinition
): Array<{ node_id: string; field: string }> {
  const graph = buildNodeGraph(workflow);
  const unused: Array<{ node_id: string; field: string }> = [];

  // 1. 收集所有输出字段
  const outputFields = new Map<string, string>(); // field -> node_id
  for (const node of workflow.nodes) {
    const outputField = getNodeOutputField(node);
    if (outputField) {
      outputFields.set(outputField, node.id);
    }
  }

  // 2. 收集所有被引用的字段
  const referencedFields = new Set<string>();
  for (const node of workflow.nodes) {
    const inputFields = getNodeInputFields(node);
    inputFields.forEach(field => referencedFields.add(field));
  }

  // 3. 找出未被引用的输出字段
  for (const [field, nodeId] of outputFields.entries()) {
    if (!referencedFields.has(field)) {
      unused.push({ node_id: nodeId, field });
    }
  }

  return unused;
}

/**
 * 验证节点是否缺少必需的输出字段定义（警告）
 *
 * LLM Agent 和 CCCC Peer 节点必须定义 output_field
 *
 * @param workflow - 工作流定义
 * @returns 警告列表
 */
export function validateRequiredOutputFields(
  workflow: WorkflowDefinition
): Array<{ node_id: string; node_type: string }> {
  const missing: Array<{ node_id: string; node_type: string }> = [];

  const requiresOutput = new Set(['llm_agent', 'script']);

  for (const node of workflow.nodes) {
    if (requiresOutput.has(node.type)) {
      const outputField = getNodeOutputField(node);
      if (!outputField) {
        missing.push({
          node_id: node.id,
          node_type: node.type
        });
      }
    }
  }

  return missing;
}

/**
 * 获取字段的来源节点
 *
 * @param workflow - 工作流定义
 * @param field - 字段名
 * @returns 产生该字段的节点 ID，如果是初始字段则返回 null
 */
export function getFieldSource(
  workflow: WorkflowDefinition,
  field: string
): string | null {
  if (INITIAL_FIELDS.has(field)) {
    return null; // 初始字段
  }

  for (const node of workflow.nodes) {
    const outputField = getNodeOutputField(node);
    if (outputField === field) {
      return node.id;
    }
  }

  return null; // 字段不存在
}
