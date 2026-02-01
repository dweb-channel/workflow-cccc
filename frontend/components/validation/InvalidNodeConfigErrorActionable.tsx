'use client';

/**
 * InvalidNodeConfigErrorActionable Component
 *
 * 显示节点配置错误，提供字段级错误列表
 * 用于显示配置验证失败的详细信息
 */

import { XCircle, AlertTriangle } from 'lucide-react';
import { Button } from '@/components/ui/button';
import type { ValidationError } from '@/lib/validation';

interface InvalidNodeConfigErrorActionableProps {
  error: ValidationError;
  onEditNode?: (nodeId: string) => void;
}

interface ConfigFieldError {
  field: string;
  issue: string;
  suggestion?: string;
}

export function InvalidNodeConfigErrorActionable({
  error,
  onEditNode
}: InvalidNodeConfigErrorActionableProps) {
  const { node_ids, message, context } = error;
  const nodeId = node_ids[0]; // 单个节点错误

  // 从 context 提取字段级错误（如果有）
  const fieldErrors: ConfigFieldError[] = [];
  if (context && typeof context === 'object') {
    // 解析 context 中的配置错误详情
    Object.entries(context).forEach(([key, value]) => {
      if (key !== 'node_id' && typeof value === 'string') {
        fieldErrors.push({
          field: key,
          issue: value,
          suggestion: undefined
        });
      }
    });
  }

  return (
    <div
      data-testid="error-actionable-invalid-node-config"
      className="border border-red-200 bg-red-50 rounded-lg p-4"
    >
      {/* Header */}
      <div className="flex items-start gap-3 mb-3">
        <XCircle className="h-5 w-5 text-red-600 flex-shrink-0 mt-0.5" />
        <div className="flex-1">
          <h4 className="text-sm font-semibold text-gray-900">
            节点配置错误
          </h4>
          <p className="text-sm text-gray-700 mt-1">
            {message}
          </p>
          <p className="text-xs text-gray-600 mt-1">
            节点 ID: <code className="bg-red-100 px-1 rounded">{nodeId}</code>
          </p>
        </div>
      </div>

      {/* Field-level Errors */}
      {fieldErrors.length > 0 && (
        <div className="ml-8 mb-3">
          <p className="text-sm font-medium text-gray-700 mb-2">
            配置问题详情:
          </p>
          <div
            data-testid="config-field-errors"
            className="bg-white rounded border border-red-200 divide-y divide-red-100"
          >
            {fieldErrors.map((fieldError, idx) => (
              <div
                key={idx}
                data-testid={`config-error-${fieldError.field}`}
                className="p-3 flex items-start gap-2"
              >
                <AlertTriangle className="h-4 w-4 text-red-500 flex-shrink-0 mt-0.5" />
                <div className="flex-1">
                  <div className="flex items-center gap-2 mb-1">
                    <code className="text-xs font-mono bg-red-100 text-red-800 px-1.5 py-0.5 rounded">
                      {fieldError.field}
                    </code>
                  </div>
                  <p className="text-sm text-gray-700">{fieldError.issue}</p>
                  {fieldError.suggestion && (
                    <p className="text-xs text-gray-600 mt-1">
                      💡 {fieldError.suggestion}
                    </p>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Edit Node Action */}
      <div className="ml-8">
        <Button
          data-testid="edit-node-config"
          onClick={() => onEditNode?.(nodeId)}
          size="sm"
        >
          编辑节点配置
        </Button>
      </div>
    </div>
  );
}
