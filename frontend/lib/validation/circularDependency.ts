/**
 * 环路检测模块
 *
 * 算法：深度优先搜索（DFS）+ 递归栈
 * 与后端 WorkflowValidator._detect_cycles() 完全对齐
 */

import type {
  WorkflowDefinition,
  ValidationError,
  CircularDependencyContext,
  NodeGraph
} from './types';
import { buildNodeGraph } from './utils';

/**
 * 检测工作流中的环路
 *
 * @param workflow - 工作流定义
 * @returns 环路错误列表（空数组表示无环路）
 *
 * 算法流程：
 * 1. 对每个未访问节点执行 DFS
 * 2. 维护递归栈（rec_stack）跟踪当前路径
 * 3. 如果节点在递归栈中 → 发现环路
 * 4. 回溯时记录环路路径
 */
export function detectCircularDependency(
  workflow: WorkflowDefinition
): ValidationError[] {
  const errors: ValidationError[] = [];
  const graph = buildNodeGraph(workflow);

  const visited = new Set<string>();
  const recStack = new Set<string>();

  /**
   * DFS 递归函数
   *
   * @param nodeId - 当前节点 ID
   * @param path - 从起点到当前节点的路径
   */
  function dfs(nodeId: string, path: string[]): void {
    // 发现环路：当前节点在递归栈中
    if (recStack.has(nodeId)) {
      const cycleStartIndex = path.indexOf(nodeId);
      const cyclePath = [...path.slice(cycleStartIndex), nodeId];

      errors.push({
        code: 'CIRCULAR_DEPENDENCY',
        message: `检测到环路：${cyclePath.join(' → ')}`,
        severity: 'error',
        node_ids: cyclePath.slice(0, -1), // 去除最后的重复节点
        context: {
          cycle_path: cyclePath
        } satisfies CircularDependencyContext
      });
      return;
    }

    // 节点已访问过（在另一条路径上），跳过
    if (visited.has(nodeId)) {
      return;
    }

    // 标记节点为已访问和在递归栈中
    visited.add(nodeId);
    recStack.add(nodeId);
    path.push(nodeId);

    // 递归访问所有邻居节点
    const neighbors = graph.edges.get(nodeId) || [];
    for (const neighbor of neighbors) {
      dfs(neighbor, [...path]);
    }

    // 回溯：从递归栈中移除
    recStack.delete(nodeId);
  }

  // 对每个未访问节点执行 DFS
  for (const node of workflow.nodes) {
    if (!visited.has(node.id)) {
      dfs(node.id, []);
    }
  }

  return errors;
}

/**
 * 快速检测是否存在环路（不返回详细路径）
 *
 * 用于实时验证的快速检查
 *
 * @param workflow - 工作流定义
 * @returns true 表示存在环路
 */
export function hasCircularDependency(workflow: WorkflowDefinition): boolean {
  const graph = buildNodeGraph(workflow);
  const visited = new Set<string>();
  const recStack = new Set<string>();

  function dfs(nodeId: string): boolean {
    if (recStack.has(nodeId)) {
      return true; // 发现环路
    }

    if (visited.has(nodeId)) {
      return false; // 已访问过，无环路
    }

    visited.add(nodeId);
    recStack.add(nodeId);

    const neighbors = graph.edges.get(nodeId) || [];
    for (const neighbor of neighbors) {
      if (dfs(neighbor)) {
        return true; // 子图中发现环路
      }
    }

    recStack.delete(nodeId);
    return false;
  }

  for (const node of workflow.nodes) {
    if (!visited.has(node.id)) {
      if (dfs(node.id)) {
        return true;
      }
    }
  }

  return false;
}

/**
 * 可视化环路路径（用于 UI 高亮）
 *
 * @param cyclePath - 环路路径（包含起点和终点重复）
 * @returns 需要高亮的边列表
 *
 * 示例：
 * cyclePath = ['node-1', 'node-2', 'node-3', 'node-1']
 * 返回：[
 *   { source: 'node-1', target: 'node-2' },
 *   { source: 'node-2', target: 'node-3' },
 *   { source: 'node-3', target: 'node-1' }
 * ]
 */
export function visualizeCyclePath(cyclePath: string[]): Array<{
  source: string;
  target: string;
}> {
  const edges: Array<{ source: string; target: string }> = [];

  for (let i = 0; i < cyclePath.length - 1; i++) {
    edges.push({
      source: cyclePath[i],
      target: cyclePath[i + 1]
    });
  }

  return edges;
}

/**
 * 建议删除哪条边可以打破环路
 *
 * 策略：删除环路中最后一条边（通常是用户刚添加的）
 *
 * @param cyclePath - 环路路径
 * @returns 建议删除的边
 */
export function suggestEdgeToRemove(cyclePath: string[]): {
  source: string;
  target: string;
  reason: string;
} {
  const lastIndex = cyclePath.length - 2;
  const source = cyclePath[lastIndex];
  const target = cyclePath[lastIndex + 1];

  return {
    source,
    target,
    reason: `删除此边可打破环路 ${cyclePath.join(' → ')}`
  };
}
