/**
 * 悬空节点检测模块
 *
 * 检测以下情况：
 * 1. 无入边且非入口点的节点（孤立节点）
 * 2. 无出边的节点（可能是终止节点，发出警告）
 *
 * 与后端 WorkflowValidator._detect_dangling_nodes() 对齐
 */

import type {
  WorkflowDefinition,
  ValidationWarning,
  ValidationError,
  DanglingNodeContext,
  NodeGraph
} from './types';
import { buildNodeGraph } from './utils';

/**
 * 检测悬空节点
 *
 * @param workflow - 工作流定义
 * @returns { errors, warnings } - 错误和警告列表
 *
 * 分类：
 * - 无入边且非入口点 → 警告（NO_INCOMING_EDGE）
 * - 无出边 → 警告（NO_OUTGOING_EDGE）
 */
export function detectDanglingNodes(
  workflow: WorkflowDefinition
): {
  errors: ValidationError[];
  warnings: ValidationWarning[];
} {
  const errors: ValidationError[] = [];
  const warnings: ValidationWarning[] = [];
  const graph = buildNodeGraph(workflow);

  for (const node of workflow.nodes) {
    const nodeId = node.id;
    const inDegree = graph.inDegree.get(nodeId) || 0;
    const outDegree = graph.outDegree.get(nodeId) || 0;

    // 1. 无入边且非入口点
    if (inDegree === 0 && nodeId !== workflow.entry_point) {
      warnings.push({
        code: 'NO_INCOMING_EDGE',
        message: `节点 '${node.label}' 无入边且非入口点，可能永远不会被执行`,
        severity: 'warning',
        node_ids: [nodeId],
        context: {
          connection_suggestions: generateConnectionSuggestions(
            nodeId,
            workflow,
            graph,
            'incoming'
          )
        } satisfies DanglingNodeContext
      });
    }

    // 2. 无出边
    if (outDegree === 0) {
      warnings.push({
        code: 'NO_OUTGOING_EDGE',
        message: `节点 '${node.label}' 无出边（可能是终止节点，请确认）`,
        severity: 'warning',
        node_ids: [nodeId],
        context: {
          connection_suggestions: generateConnectionSuggestions(
            nodeId,
            workflow,
            graph,
            'outgoing'
          )
        } satisfies DanglingNodeContext
      });
    }
  }

  return { errors, warnings };
}

/**
 * 生成节点连接建议
 *
 * @param nodeId - 目标节点 ID
 * @param workflow - 工作流定义
 * @param graph - 节点图
 * @param direction - 连接方向（incoming: 建议谁连到该节点, outgoing: 建议该节点连到谁）
 * @returns 建议的节点 ID 列表
 *
 * 策略：
 * - incoming: 建议入口点或无出边的节点连接到该节点
 * - outgoing: 建议该节点连接到无入边的节点或创建 __END__ 边
 */
function generateConnectionSuggestions(
  nodeId: string,
  workflow: WorkflowDefinition,
  graph: NodeGraph,
  direction: 'incoming' | 'outgoing'
): string[] {
  const suggestions: string[] = [];

  if (direction === 'incoming') {
    // 建议哪些节点可以连接到该节点
    for (const node of workflow.nodes) {
      if (node.id === nodeId) continue;

      // 策略 1: 入口点（如果该节点可以作为第一步）
      if (node.id === workflow.entry_point) {
        suggestions.push(node.id);
      }

      // 策略 2: 无出边的节点（可能需要后续步骤）
      const outDegree = graph.outDegree.get(node.id) || 0;
      if (outDegree === 0) {
        suggestions.push(node.id);
      }
    }
  } else {
    // 建议该节点可以连接到哪些节点
    for (const node of workflow.nodes) {
      if (node.id === nodeId) continue;

      // 策略 1: 无入边的节点（孤立节点）
      const inDegree = graph.inDegree.get(node.id) || 0;
      if (inDegree === 0 && node.id !== workflow.entry_point) {
        suggestions.push(node.id);
      }
    }

    // 策略 2: 如果没有建议，推荐连接到 __END__（终止节点）
    if (suggestions.length === 0) {
      suggestions.push('__END__');
    }
  }

  return suggestions;
}

/**
 * 检测孤立子图（一组节点彼此连接，但与主图断开）
 *
 * @param workflow - 工作流定义
 * @returns 孤立子图列表，每个子图是节点 ID 数组
 *
 * 算法：从入口点 DFS，找出所有可达节点，剩余节点构成孤立子图
 */
export function detectIsolatedSubgraphs(
  workflow: WorkflowDefinition
): string[][] {
  const graph = buildNodeGraph(workflow);
  const reachable = new Set<string>();

  // DFS 从入口点遍历
  function dfs(nodeId: string) {
    if (reachable.has(nodeId)) return;
    reachable.add(nodeId);

    const neighbors = graph.edges.get(nodeId) || [];
    for (const neighbor of neighbors) {
      dfs(neighbor);
    }
  }

  dfs(workflow.entry_point);

  // 找出不可达节点
  const unreachable = workflow.nodes
    .map(n => n.id)
    .filter(id => !reachable.has(id));

  if (unreachable.length === 0) {
    return []; // 无孤立子图
  }

  // 将不可达节点分组为连通子图
  const subgraphs: string[][] = [];
  const visited = new Set<string>();

  function exploreSubgraph(startNodeId: string): string[] {
    const subgraph: string[] = [];
    const stack = [startNodeId];

    while (stack.length > 0) {
      const nodeId = stack.pop()!;
      if (visited.has(nodeId)) continue;

      visited.add(nodeId);
      subgraph.push(nodeId);

      // 探索双向边（正向 + 反向）
      const neighbors = [
        ...(graph.edges.get(nodeId) || []),
        ...(graph.reverseEdges.get(nodeId) || [])
      ];

      for (const neighbor of neighbors) {
        if (unreachable.includes(neighbor) && !visited.has(neighbor)) {
          stack.push(neighbor);
        }
      }
    }

    return subgraph;
  }

  for (const nodeId of unreachable) {
    if (!visited.has(nodeId)) {
      const subgraph = exploreSubgraph(nodeId);
      subgraphs.push(subgraph);
    }
  }

  return subgraphs;
}

/**
 * 快速检测是否存在悬空节点（不返回详细信息）
 *
 * 用于实时验证的快速检查
 *
 * @param workflow - 工作流定义
 * @returns true 表示存在悬空节点
 */
export function hasDanglingNodes(workflow: WorkflowDefinition): boolean {
  const graph = buildNodeGraph(workflow);

  for (const node of workflow.nodes) {
    const inDegree = graph.inDegree.get(node.id) || 0;
    const outDegree = graph.outDegree.get(node.id) || 0;

    // 无入边且非入口点，或无出边
    if (
      (inDegree === 0 && node.id !== workflow.entry_point) ||
      outDegree === 0
    ) {
      return true;
    }
  }

  return false;
}
