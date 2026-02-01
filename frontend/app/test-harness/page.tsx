'use client';

/**
 * Validation Test Harness Page
 *
 * E2E 测试页面 - 用于 Playwright 测试
 * 加载 Fixture 数据并运行验证器
 */

import { useState } from 'react';
import { validateWorkflowClient } from '@/lib/validation';
import { FixtureLoader } from '@/tests/fixtures/FixtureLoader';
import { adaptFixtureWorkflow } from '@/lib/validation';
import type { ValidationResult, ValidationError, ValidationWarning } from '@/lib/validation';
import {
  ValidationStatusBadge,
  MissingFieldReferenceErrorActionable,
  CircularDependencyErrorActionable,
  DanglingNodeWarningActionable,
  InvalidNodeConfigErrorActionable,
  JumpReferenceWarningActionable
} from '@/components/validation';
import {
  isMissingFieldReferenceError,
  isCircularDependencyError,
  isDanglingNodeWarning
} from '@/lib/validation';

export default function TestHarnessPage() {
  const [selectedFixture, setSelectedFixture] = useState('');
  const [validationResult, setValidationResult] = useState<ValidationResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [actionLog, setActionLog] = useState<string[]>([]);

  // 获取所有测试用例
  const testCases = FixtureLoader.getAllTestCases();

  const runValidation = () => {
    setError(null);
    setValidationResult(null);

    if (!selectedFixture) {
      setError('请选择测试场景');
      return;
    }

    try {
      // 加载 fixture 数据
      const fixture = FixtureLoader.getTestCase(selectedFixture);
      if (!fixture) {
        setError(`测试场景 ${selectedFixture} 未找到`);
        return;
      }

      // 转换工作流格式
      const workflow = adaptFixtureWorkflow(fixture.workflow);

      // 运行验证
      const result = validateWorkflowClient(workflow);

      setValidationResult(result);
    } catch (err) {
      setError(err instanceof Error ? err.message : '验证过程出错');
    }
  };

  const clearResult = () => {
    setValidationResult(null);
    setError(null);
    setSelectedFixture('');
    setActionLog([]);
  };

  // Interactive action handlers (for demonstration)
  const handleFixField = (nodeId: string, oldField: string, newField: string) => {
    const msg = `修复字段: 节点 ${nodeId} - 从 "${oldField}" 改为 "${newField}"`;
    setActionLog(prev => [...prev, msg]);
    console.log(msg);
  };

  const handleBreakCycle = (sourceNode: string, targetNode: string) => {
    const msg = `打断循环: 删除 ${sourceNode} → ${targetNode}`;
    setActionLog(prev => [...prev, msg]);
    console.log(msg);
  };

  const handleConnectNode = (nodeId: string, targetNodeId: string) => {
    const msg = `连接节点: ${nodeId} → ${targetNodeId}`;
    setActionLog(prev => [...prev, msg]);
    console.log(msg);
  };

  const handleEditNode = (nodeId: string) => {
    const msg = `编辑节点: ${nodeId}`;
    setActionLog(prev => [...prev, msg]);
    console.log(msg);
  };

  const handleFixJumpTarget = (nodeId: string, jumpTargetId: string) => {
    const msg = `修正跳转: 节点 ${nodeId} - 目标 ${jumpTargetId}`;
    setActionLog(prev => [...prev, msg]);
    console.log(msg);
  };

  // Helper to render ErrorActionable components
  const renderErrorActionable = (error: ValidationError, idx: number) => {
    if (isMissingFieldReferenceError(error)) {
      return (
        <MissingFieldReferenceErrorActionable
          key={idx}
          error={error}
          onFixField={handleFixField}
        />
      );
    }
    if (isCircularDependencyError(error)) {
      return (
        <CircularDependencyErrorActionable
          key={idx}
          error={error}
          onBreakCycle={handleBreakCycle}
        />
      );
    }
    if (error.code === 'INVALID_NODE_CONFIG') {
      return (
        <InvalidNodeConfigErrorActionable
          key={idx}
          error={error}
          onEditNode={handleEditNode}
        />
      );
    }
    // Fallback for other error types
    return (
      <div
        key={idx}
        data-testid={`validation-error-${error.code.toLowerCase()}`}
        className="border border-red-200 bg-red-50 rounded-md p-4"
      >
        <div className="flex items-start gap-3">
          <span className="text-red-600 font-mono text-sm">{error.code}</span>
          <div className="flex-1">
            <p className="text-gray-900">{error.message}</p>
            <p className="text-sm text-gray-600 mt-1">
              节点: {error.node_ids.join(', ')}
            </p>
          </div>
        </div>
      </div>
    );
  };

  const renderWarningActionable = (warning: ValidationWarning, idx: number) => {
    if (isDanglingNodeWarning(warning)) {
      return (
        <DanglingNodeWarningActionable
          key={idx}
          warning={warning}
          onConnectNode={handleConnectNode}
        />
      );
    }
    if (warning.code === 'UNUSED_OUTPUT_FIELD') {
      return (
        <JumpReferenceWarningActionable
          key={idx}
          warning={warning}
          onFixJumpTarget={handleFixJumpTarget}
        />
      );
    }
    // Fallback for other warning types
    return (
      <div
        key={idx}
        data-testid={`validation-warning-${warning.code.toLowerCase()}`}
        className="border border-yellow-200 bg-yellow-50 rounded-md p-4"
      >
        <div className="flex items-start gap-3">
          <span className="text-yellow-700 font-mono text-sm">{warning.code}</span>
          <div className="flex-1">
            <p className="text-gray-900">{warning.message}</p>
            <p className="text-sm text-gray-600 mt-1">
              节点: {warning.node_ids.join(', ')}
            </p>
          </div>
        </div>
      </div>
    );
  };

  return (
    <div className="min-h-screen bg-gray-50 py-8 px-4">
      <div className="max-w-5xl mx-auto">
        <div className="bg-white rounded-lg shadow-sm p-8">
          {/* Header */}
          <div className="mb-8">
            <h1 className="text-3xl font-bold text-gray-900 mb-2">
              Workflow Validation Test Harness
            </h1>
            <p className="text-gray-600">
              E2E 测试工具 - 用于 Playwright 自动化测试
            </p>
          </div>

          {/* Controls */}
          <div className="mb-6 flex gap-4 items-start flex-wrap">
            <div className="flex-1 min-w-[300px]">
              <label
                htmlFor="fixture-selector"
                className="block text-sm font-medium text-gray-700 mb-2"
              >
                选择测试场景
              </label>
              <select
                id="fixture-selector"
                data-testid="fixture-selector"
                className="w-full px-4 py-2 border border-gray-300 rounded-md focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                value={selectedFixture}
                onChange={(e) => setSelectedFixture(e.target.value)}
              >
                <option value="">-- 选择测试场景 --</option>
                {testCases.map((tc) => (
                  <option key={tc.id} value={tc.id}>
                    {tc.id} ({tc.priority}) - {tc.description.substring(0, 50)}...
                  </option>
                ))}
              </select>
            </div>

            <div className="flex gap-2">
              <button
                data-testid="run-validation"
                onClick={runValidation}
                disabled={!selectedFixture}
                className="px-6 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700 disabled:bg-gray-400 disabled:cursor-not-allowed transition-colors"
              >
                运行验证
              </button>
              <button
                data-testid="clear-result"
                onClick={clearResult}
                className="px-6 py-2 bg-gray-200 text-gray-700 rounded-md hover:bg-gray-300 transition-colors"
              >
                清除结果
              </button>
            </div>
          </div>

          {/* Error Display */}
          {error && (
            <div
              data-testid="validation-error"
              className="mb-6 p-4 bg-red-50 border border-red-200 rounded-md"
            >
              <p className="text-red-800 font-medium">错误</p>
              <p className="text-red-600">{error}</p>
            </div>
          )}

          {/* Result Display */}
          {validationResult && (
            <div data-testid="validation-result" className="space-y-4">
              {/* Summary with Badge */}
              <div className="bg-gray-50 rounded-md p-4">
                <div className="flex items-center justify-between mb-4">
                  <h2 className="text-xl font-semibold text-gray-900">
                    验证结果
                  </h2>
                  <ValidationStatusBadge
                    status={
                      validationResult.valid
                        ? 'valid'
                        : validationResult.errors.length > 0
                        ? 'error'
                        : 'warning'
                    }
                    errorCount={validationResult.errors.length}
                    warningCount={validationResult.warnings.length}
                  />
                </div>
                <div className="grid grid-cols-3 gap-4">
                  <div>
                    <p className="text-sm text-gray-600 mb-1">有效性</p>
                    <p
                      data-testid="validation-valid"
                      className={`text-lg font-semibold ${
                        validationResult.valid ? 'text-green-600' : 'text-red-600'
                      }`}
                    >
                      {validationResult.valid ? '✓ 有效' : '✗ 无效'}
                    </p>
                  </div>
                  <div>
                    <p className="text-sm text-gray-600 mb-1">错误数量</p>
                    <p
                      data-testid="validation-error-count"
                      className="text-lg font-semibold text-gray-900"
                    >
                      {validationResult.errors.length}
                    </p>
                  </div>
                  <div>
                    <p className="text-sm text-gray-600 mb-1">警告数量</p>
                    <p
                      data-testid="validation-warning-count"
                      className="text-lg font-semibold text-gray-900"
                    >
                      {validationResult.warnings.length}
                    </p>
                  </div>
                </div>
              </div>

              {/* Errors with Actionable Components */}
              {validationResult.errors.length > 0 && (
                <div>
                  <h3 className="text-lg font-semibold text-gray-900 mb-3">
                    错误列表 (可交互修复)
                  </h3>
                  <div className="space-y-3">
                    {validationResult.errors.map((error, idx) =>
                      renderErrorActionable(error, idx)
                    )}
                  </div>
                </div>
              )}

              {/* Warnings with Actionable Components */}
              {validationResult.warnings.length > 0 && (
                <div>
                  <h3 className="text-lg font-semibold text-gray-900 mb-3">
                    警告列表 (可交互修复)
                  </h3>
                  <div className="space-y-3">
                    {validationResult.warnings.map((warning, idx) =>
                      renderWarningActionable(warning, idx)
                    )}
                  </div>
                </div>
              )}

              {/* Action Log */}
              {actionLog.length > 0 && (
                <div>
                  <h3 className="text-lg font-semibold text-gray-900 mb-3">
                    交互操作日志
                  </h3>
                  <div
                    data-testid="action-log"
                    className="bg-gray-50 rounded-md p-4 space-y-1"
                  >
                    {actionLog.map((log, idx) => (
                      <div
                        key={idx}
                        className="text-sm text-gray-700 font-mono"
                      >
                        {idx + 1}. {log}
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Raw JSON */}
              <details>
                <summary className="cursor-pointer text-sm text-gray-700 hover:text-gray-900 font-medium">
                  查看完整 JSON 结果
                </summary>
                <pre
                  data-testid="validation-result-json"
                  className="mt-3 bg-gray-100 p-4 rounded-md overflow-x-auto text-xs"
                >
                  {JSON.stringify(validationResult, null, 2)}
                </pre>
              </details>
            </div>
          )}

          {/* Fixture Info */}
          {selectedFixture && (
            <div className="mt-8 pt-6 border-t border-gray-200">
              <details>
                <summary className="cursor-pointer text-sm text-gray-700 hover:text-gray-900 font-medium">
                  Fixture 信息
                </summary>
                <div className="mt-3 space-y-2 text-sm">
                  {(() => {
                    const fixture = FixtureLoader.getTestCase(selectedFixture);
                    return fixture ? (
                      <>
                        <p>
                          <strong>ID:</strong> {fixture.id}
                        </p>
                        <p>
                          <strong>优先级:</strong> {fixture.priority}
                        </p>
                        <p>
                          <strong>Phase:</strong> {fixture.phase}
                        </p>
                        <p>
                          <strong>标签:</strong> {fixture.tags.join(', ')}
                        </p>
                        <p>
                          <strong>描述:</strong> {fixture.description}
                        </p>
                      </>
                    ) : null;
                  })()}
                </div>
              </details>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="mt-6 text-center text-sm text-gray-500">
          <p>
            Fixture Version: {FixtureLoader.getMetadata().version} | Last
            Updated: {FixtureLoader.getMetadata().lastUpdated}
          </p>
          <p className="mt-1">
            用于 Playwright E2E 测试 - Phase 1 TDD
          </p>
        </div>
      </div>
    </div>
  );
}
