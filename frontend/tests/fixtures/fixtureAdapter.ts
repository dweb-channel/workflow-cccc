/**
 * Fixture Adapter
 *
 * 桥接 fixture 格式与 frontend WorkflowDefinition 类型
 *
 * 背景：
 * - Fixture v1.0 使用简化结构（name, nodes, edges）
 * - Frontend 需要完整 WorkflowDefinition（id, title, entry_point, status, nodes, edges）
 *
 * 解决方案：
 * - v1.0: 使用 adapter 函数自动补充缺失字段
 * - v1.1: 更新 fixture 添加完整字段，移除此 adapter
 */

import type {
  WorkflowDefinition,
  NodeDefinition,
  EdgeDefinition
} from '@/lib/validation/types';

/**
 * Fixture 工作流格式（简化版）
 */
interface FixtureWorkflow {
  name: string;
  nodes: NodeDefinition[];
  edges: EdgeDefinition[];
}

/**
 * 将 fixture 工作流转换为 WorkflowDefinition
 *
 * @param fixtureWorkflow - Fixture 中的工作流对象
 * @returns 完整的 WorkflowDefinition 对象
 *
 * 转换规则：
 * - id: 使用 "test-{name}" 格式
 * - title: 使用 name 字段
 * - entry_point: 自动检测入度为 0 的节点
 * - status: 默认为 'draft'
 * - nodes/edges: 直接使用原始数据
 */
export function adaptFixtureWorkflow(
  fixtureWorkflow: FixtureWorkflow
): WorkflowDefinition {
  return {
    id: `test-${fixtureWorkflow.name}`,
    title: fixtureWorkflow.name,
    entry_point: findEntryNode(fixtureWorkflow.nodes, fixtureWorkflow.edges),
    status: 'draft',
    nodes: fixtureWorkflow.nodes,
    edges: fixtureWorkflow.edges
  };
}

/**
 * 自动检测入口节点（入度为 0 的节点）
 *
 * @param nodes - 节点列表
 * @param edges - 边列表
 * @returns 入口节点 ID
 *
 * 算法：
 * 1. 收集所有节点 ID
 * 2. 收集所有边的 target（入边的目标节点）
 * 3. 找出不在 target 集合中的节点（即入度为 0）
 * 4. 如果有多个入度为 0 的节点，返回第一个
 * 5. 如果没有（环路情况），返回第一个节点作为 fallback
 */
export function findEntryNode(
  nodes: NodeDefinition[],
  edges: EdgeDefinition[]
): string {
  if (nodes.length === 0) {
    throw new Error('Workflow must have at least one node');
  }

  // 收集所有节点 ID
  const nodeIds = new Set(nodes.map(n => n.id));

  // 收集所有边的 target（有入边的节点）
  const targetIds = new Set(edges.map(e => e.target));

  // 找出入度为 0 的节点
  for (const nodeId of nodeIds) {
    if (!targetIds.has(nodeId)) {
      return nodeId;
    }
  }

  // Fallback: 如果所有节点都有入边（环路情况），返回第一个节点
  return nodes[0].id;
}

/**
 * 批量转换 fixture 测试用例
 *
 * @param fixtures - Fixture 文件内容
 * @returns 转换后的测试用例列表
 *
 * 用途：
 * - 从 validation_test_cases.json 加载测试用例
 * - 批量转换所有工作流定义
 */
export function adaptFixtureTestCases(fixtures: {
  validation_test_cases: Array<{
    id: string;
    workflow: FixtureWorkflow;
    expected_validation_result: any;
    [key: string]: any;
  }>;
}): Array<{
  id: string;
  workflow: WorkflowDefinition;
  expected_validation_result: any;
  [key: string]: any;
}> {
  return fixtures.validation_test_cases.map(testCase => ({
    ...testCase,
    workflow: adaptFixtureWorkflow(testCase.workflow)
  }));
}
