/**
 * 验证工具函数
 *
 * 提供图构建、字段提取等公共功能
 */

import type {
  WorkflowDefinition,
  NodeGraph,
  NodeDefinition,
  EdgeDefinition
} from './types';
import { SPECIAL_NODES } from './types';

/**
 * 从工作流定义构建节点图
 *
 * @param workflow - 工作流定义
 * @returns 节点图（包含正向边、反向边、入度、出度）
 */
export function buildNodeGraph(workflow: WorkflowDefinition): NodeGraph {
  const nodes = new Map<string, NodeDefinition>();
  const edges = new Map<string, string[]>();
  const reverseEdges = new Map<string, string[]>();
  const inDegree = new Map<string, number>();
  const outDegree = new Map<string, number>();

  // 初始化节点
  for (const node of workflow.nodes) {
    nodes.set(node.id, node);
    edges.set(node.id, []);
    reverseEdges.set(node.id, []);
    inDegree.set(node.id, 0);
    outDegree.set(node.id, 0);
  }

  // 构建边关系
  for (const edge of workflow.edges) {
    const { source, target } = edge;

    // 跳过指向 __END__ 的边（不影响图结构）
    if (target === SPECIAL_NODES.END) {
      continue;
    }

    // 添加正向边
    const sourceTargets = edges.get(source) || [];
    sourceTargets.push(target);
    edges.set(source, sourceTargets);

    // 添加反向边
    const targetSources = reverseEdges.get(target) || [];
    targetSources.push(source);
    reverseEdges.set(target, targetSources);

    // 更新度数
    outDegree.set(source, (outDegree.get(source) || 0) + 1);
    inDegree.set(target, (inDegree.get(target) || 0) + 1);
  }

  return {
    nodes,
    edges,
    reverseEdges,
    inDegree,
    outDegree
  };
}

/**
 * 拓扑排序（Kahn 算法）
 *
 * @param workflow - 工作流定义
 * @returns 拓扑排序结果，如果有环路则返回 null
 *
 * 算法流程：
 * 1. 找到所有入度为 0 的节点（起点）
 * 2. 从队列中取出节点，加入排序结果
 * 3. 将该节点的所有邻居的入度 -1
 * 4. 如果邻居入度变为 0，加入队列
 * 5. 重复直到队列为空
 * 6. 如果排序结果包含所有节点 → 无环路，否则有环路
 */
export function topologicalSort(
  workflow: WorkflowDefinition
): string[] | null {
  const graph = buildNodeGraph(workflow);
  const inDegreeMap = new Map(graph.inDegree);
  const queue: string[] = [];

  // 找到入口节点（从 entry_point 开始）
  if (inDegreeMap.get(workflow.entry_point) === 0) {
    queue.push(workflow.entry_point);
  } else {
    // 入口节点有入边，说明可能有环路或入口点设置错误
    return null;
  }

  const sorted: string[] = [];

  while (queue.length > 0) {
    const nodeId = queue.shift()!;
    sorted.push(nodeId);

    const neighbors = graph.edges.get(nodeId) || [];
    for (const neighbor of neighbors) {
      const newInDegree = (inDegreeMap.get(neighbor) || 0) - 1;
      inDegreeMap.set(neighbor, newInDegree);

      if (newInDegree === 0) {
        queue.push(neighbor);
      }
    }
  }

  // 检查是否所有节点都被访问
  if (sorted.length !== workflow.nodes.length) {
    return null; // 有环路或孤立节点
  }

  return sorted;
}

/**
 * 提取模板字符串中的字段引用
 *
 * 支持 {field} 和 {{node.field}} 语法
 *
 * @param template - 模板字符串
 * @returns 字段名集合
 *
 * 示例：
 * extractTemplateFields("根据 {request} 制定计划")
 * → Set(['request'])
 *
 * extractTemplateFields("{{node-1.result}}")
 * → Set(['node-1.result'])
 */
export function extractTemplateFields(template: string): Set<string> {
  const fields = new Set<string>();

  // 支持 {{node.field}} 语法（fixture 格式）
  const doublePattern = /\{\{([a-zA-Z0-9_\-\.]+)\}\}/g;
  let match: RegExpExecArray | null;
  while ((match = doublePattern.exec(template)) !== null) {
    fields.add(match[1]);
  }

  // 支持 {field} 语法（标准格式）
  const singlePattern = /\{([a-zA-Z0-9_\-\.]+)\}/g;
  while ((match = singlePattern.exec(template)) !== null) {
    // 避免重复添加（如果已经通过 {{}} 匹配过）
    if (!fields.has(match[1])) {
      fields.add(match[1]);
    }
  }

  return fields;
}

/**
 * 获取节点的所有输入字段
 *
 * 包括：
 * 1. config.input_fields 中明确声明的字段（数组）
 * 2. config.input_field 中声明的字段（单个字段，fixture 格式）
 * 3. prompt_template 中引用的字段（{field} 或 {{field}} 语法）
 *
 * @param node - 节点定义
 * @returns 输入字段集合
 */
export function getNodeInputFields(node: NodeDefinition): Set<string> {
  const inputFields = new Set<string>();

  // 1. 明确声明的输入字段（数组）
  const declaredInputs = node.config.input_fields as string[] | undefined;
  if (Array.isArray(declaredInputs)) {
    declaredInputs.forEach(field => inputFields.add(field));
  }

  // 2. 单个输入字段（fixture 格式）
  const singleInput = node.config.input_field as string | undefined;
  if (typeof singleInput === 'string') {
    // 提取 {{node.field}} 格式的引用
    const extractedFields = extractTemplateFields(singleInput);
    extractedFields.forEach(field => inputFields.add(field));
  }

  // 3. prompt_template 中引用的字段
  const promptTemplate = node.config.prompt_template as string | undefined;
  if (typeof promptTemplate === 'string') {
    const templateFields = extractTemplateFields(promptTemplate);
    templateFields.forEach(field => inputFields.add(field));
  }

  // 4. 其他节点类型特定的字段引用
  // TODO: 根据不同节点类型（conditional, script）提取字段

  return inputFields;
}

/**
 * 获取节点的输出字段
 *
 * @param node - 节点定义
 * @returns 输出字段名，如果节点无输出则返回 null
 */
export function getNodeOutputField(node: NodeDefinition): string | null {
  return (node.config.output_field as string) || null;
}

/**
 * 查找入口节点（无入边的节点）
 *
 * @param workflow - 工作流定义
 * @returns 入口节点 ID，如果有多个或没有则返回 null
 */
export function findEntryNode(workflow: WorkflowDefinition): string | null {
  const graph = buildNodeGraph(workflow);
  const entryNodes: string[] = [];

  for (const [nodeId, inDegree] of graph.inDegree.entries()) {
    if (inDegree === 0) {
      entryNodes.push(nodeId);
    }
  }

  // 必须有且只有一个入口节点
  if (entryNodes.length !== 1) {
    return null;
  }

  return entryNodes[0];
}

/**
 * 获取节点的所有上游节点（递归）
 *
 * @param nodeId - 节点 ID
 * @param graph - 节点图
 * @returns 所有上游节点 ID 集合
 */
export function getUpstreamNodes(
  nodeId: string,
  graph: NodeGraph
): Set<string> {
  const upstream = new Set<string>();
  const visited = new Set<string>();

  function dfs(id: string) {
    if (visited.has(id)) return;
    visited.add(id);

    const sources = graph.reverseEdges.get(id) || [];
    for (const source of sources) {
      upstream.add(source);
      dfs(source);
    }
  }

  dfs(nodeId);
  return upstream;
}

/**
 * 获取节点的直接上游节点（非递归）
 *
 * @param nodeId - 节点 ID
 * @param graph - 节点图
 * @returns 直接上游节点 ID 数组
 */
export function getDirectUpstreamNodes(
  nodeId: string,
  graph: NodeGraph
): string[] {
  return graph.reverseEdges.get(nodeId) || [];
}
