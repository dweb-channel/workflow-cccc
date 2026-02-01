/**
 * validateWorkflowClient() 测试套件
 *
 * 使用 Fixture v1.0 的测试场景验证验证器功能
 *
 * 测试策略：
 * - 加载 fixture 测试场景
 * - 使用 fixtureAdapter 转换工作流格式
 * - 运行 validateWorkflowClient()
 * - 比较结果与 expected_validation_result
 *
 * SSOT 验证：确保前端验证器与 fixture 完全对齐
 */

import { describe, it, expect } from 'vitest';
import { validateWorkflowClient, getValidationSummary } from '../validator';
import { adaptFixtureWorkflow } from '../../../tests/fixtures/fixtureAdapter';
import fixturesData from '../../../../tests/fixtures/validation_test_cases.json';

describe('validateWorkflowClient', () => {
  describe('Fixture v1.0 场景测试', () => {
    it('应该检测到环路依赖 (circular_dependency)', () => {
      // 加载 fixture 测试场景
      const fixture = fixturesData.validation_test_cases.find(
        tc => tc.id === 'circular_dependency'
      );
      expect(fixture).toBeDefined();

      // 使用 adapter 转换工作流格式
      const workflow = adaptFixtureWorkflow(fixture!.workflow);

      // 运行验证器
      const result = validateWorkflowClient(workflow);

      // 验证结果应该与 expected_validation_result 对齐
      expect(result.valid).toBe(false);
      expect(result.errors).toHaveLength(1);
      expect(result.errors[0].code).toBe('CIRCULAR_DEPENDENCY');
      expect(result.errors[0].severity).toBe('error');

      // 验证 Context 字段契约
      expect(result.errors[0].context).toBeDefined();
      expect(result.errors[0].context!.cycle_path).toBeDefined();
      expect(result.errors[0].context!.cycle_path.length).toBeGreaterThanOrEqual(
        3
      );

      // 验证环路路径包含重复的起始节点
      const cyclePath = result.errors[0].context!.cycle_path;
      expect(cyclePath[0]).toBe(cyclePath[cyclePath.length - 1]);
    });

    it('应该检测到缺失的字段引用 (missing_field_reference)', () => {
      const fixture = fixturesData.validation_test_cases.find(
        tc => tc.id === 'missing_field_reference'
      );
      expect(fixture).toBeDefined();

      const workflow = adaptFixtureWorkflow(fixture!.workflow);
      const result = validateWorkflowClient(workflow);

      expect(result.valid).toBe(false);
      expect(result.errors).toHaveLength(1);
      expect(result.errors[0].code).toBe('MISSING_FIELD_REFERENCE');
      expect(result.errors[0].severity).toBe('error');

      // 验证 Context 字段契约（零防御性检查保证）
      expect(result.errors[0].context).toBeDefined();
      expect(result.errors[0].context!.available_fields).toBeDefined();
      expect(result.errors[0].context!.available_fields.length).toBeGreaterThan(
        0
      ); // 保证非空
      expect(result.errors[0].context!.field).toBeDefined();
      expect(result.errors[0].context!.upstream_node_ids).toBeDefined();
    });

    it('应该检测到悬空节点 (dangling_node)', () => {
      const fixture = fixturesData.validation_test_cases.find(
        tc => tc.id === 'dangling_node'
      );
      expect(fixture).toBeDefined();

      const workflow = adaptFixtureWorkflow(fixture!.workflow);
      const result = validateWorkflowClient(workflow);

      // 悬空节点是警告，不是错误
      expect(result.valid).toBe(true);
      expect(result.errors).toHaveLength(0);
      expect(result.warnings.length).toBeGreaterThan(0);

      // 查找悬空节点警告
      const danglingWarning = result.warnings.find(
        w => w.code === 'NO_INCOMING_EDGE' || w.code === 'NO_OUTGOING_EDGE'
      );
      expect(danglingWarning).toBeDefined();
      expect(danglingWarning!.severity).toBe('warning');

      // 验证 Context 字段（connection_suggestions 是可选的）
      if (danglingWarning!.context?.connection_suggestions) {
        expect(
          danglingWarning!.context.connection_suggestions.length
        ).toBeGreaterThan(0);
      }
    });

    // 注意：以下两个测试场景需要额外的验证器实现
    // 目前我们专注于 Phase 1 的核心场景

    it.skip('应该检测到无效的节点配置 (invalid_node_config)', () => {
      // TODO: 需要实现 JSON Schema 验证器
      const fixture = fixturesData.validation_test_cases.find(
        tc => tc.id === 'invalid_node_config'
      );
      expect(fixture).toBeDefined();

      const workflow = adaptFixtureWorkflow(fixture!.workflow);
      const result = validateWorkflowClient(workflow);

      expect(result.valid).toBe(false);
      expect(result.errors).toHaveLength(1);
      expect(result.errors[0].code).toBe('INVALID_NODE_CONFIG');
    });

    it.skip('应该检测到跳跃引用 (jump_reference)', () => {
      // TODO: 需要实现路径分析验证器
      const fixture = fixturesData.validation_test_cases.find(
        tc => tc.id === 'jump_reference'
      );
      expect(fixture).toBeDefined();

      const workflow = adaptFixtureWorkflow(fixture!.workflow);
      const result = validateWorkflowClient(workflow);

      expect(result.valid).toBe(true); // 跳跃引用是警告
      expect(result.warnings.length).toBeGreaterThan(0);

      const jumpWarning = result.warnings.find(
        w => w.code === 'JUMP_REFERENCE'
      );
      expect(jumpWarning).toBeDefined();
    });
  });

  describe('辅助函数测试', () => {
    it('getValidationSummary 应该返回正确的摘要', () => {
      const fixture = fixturesData.validation_test_cases.find(
        tc => tc.id === 'circular_dependency'
      );
      const workflow = adaptFixtureWorkflow(fixture!.workflow);
      const result = validateWorkflowClient(workflow);

      const summary = getValidationSummary(result);

      expect(summary.valid).toBe(false);
      expect(summary.errorCount).toBe(1);
      expect(summary.hasCircularDependency).toBe(true);
      expect(summary.hasFieldErrors).toBe(false);
    });

    it('getValidationSummary 应该正确统计警告', () => {
      const fixture = fixturesData.validation_test_cases.find(
        tc => tc.id === 'dangling_node'
      );
      const workflow = adaptFixtureWorkflow(fixture!.workflow);
      const result = validateWorkflowClient(workflow);

      const summary = getValidationSummary(result);

      expect(summary.valid).toBe(true);
      expect(summary.warningCount).toBeGreaterThan(0);
      expect(summary.hasDanglingNodes).toBe(true);
    });
  });

  describe('边界情况测试', () => {
    it('空工作流应该通过验证', () => {
      const emptyWorkflow = {
        id: 'test-empty',
        title: 'Empty Workflow',
        entry_point: 'node-1',
        status: 'draft' as const,
        nodes: [
          {
            id: 'node-1',
            type: 'llm_agent',
            label: 'Start',
            config: {}
          }
        ],
        edges: []
      };

      const result = validateWorkflowClient(emptyWorkflow);

      // 空工作流可能有悬空节点警告，但应该 valid
      expect(result.valid).toBe(true);
      expect(result.errors).toHaveLength(0);
    });

    it('单节点工作流应该通过验证', () => {
      const singleNodeWorkflow = {
        id: 'test-single',
        title: 'Single Node Workflow',
        entry_point: 'node-1',
        status: 'draft' as const,
        nodes: [
          {
            id: 'node-1',
            type: 'llm_agent',
            label: 'Single Node',
            config: {
              output_field: 'result'
            }
          }
        ],
        edges: []
      };

      const result = validateWorkflowClient(singleNodeWorkflow);

      expect(result.valid).toBe(true);
      expect(result.errors).toHaveLength(0);
    });
  });
});
