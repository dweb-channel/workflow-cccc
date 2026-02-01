'use client';

/**
 * DanglingNodeWarningActionable Component
 *
 * 显示无连接节点的警告，并提供连接建议
 * 基于 Context 字段契约：connection_suggestions 可选但保证非空
 */

import { AlertCircle } from 'lucide-react';
import { Button } from '@/components/ui/button';
import type { ValidationWarning, DanglingNodeContext } from '@/lib/validation';

interface DanglingNodeWarningActionableProps {
  warning: ValidationWarning & { context: DanglingNodeContext };
  onConnectNode?: (nodeId: string, targetNodeId: string) => void;
}

export function DanglingNodeWarningActionable({
  warning,
  onConnectNode
}: DanglingNodeWarningActionableProps) {
  const { node_ids, message, context } = warning;
  const nodeId = node_ids[0]; // 单个节点警告
  const suggestions = context.connection_suggestions;

  return (
    <div
      data-testid="warning-actionable-dangling-node"
      className="border border-yellow-200 bg-yellow-50 rounded-lg p-4"
    >
      {/* Header */}
      <div className="flex items-start gap-3 mb-3">
        <AlertCircle className="h-5 w-5 text-yellow-600 flex-shrink-0 mt-0.5" />
        <div className="flex-1">
          <h4 className="text-sm font-semibold text-gray-900">
            节点未连接
          </h4>
          <p className="text-sm text-gray-700 mt-1">
            {message}
          </p>
          <p className="text-xs text-gray-600 mt-1">
            节点 ID: <code className="bg-yellow-100 px-1 rounded">{nodeId}</code>
          </p>
        </div>
      </div>

      {/* Connection Suggestions */}
      {suggestions && suggestions.length > 0 && (
        <div className="ml-8 space-y-2">
          <p className="text-sm font-medium text-gray-700">建议连接到：</p>
          <div
            data-testid="connection-suggestions"
            className="flex flex-wrap gap-2"
          >
            {suggestions.map((targetNodeId) => (
              <Button
                key={targetNodeId}
                data-testid={`connect-to-${targetNodeId}`}
                variant="secondary"
                size="sm"
                onClick={() => onConnectNode?.(nodeId, targetNodeId)}
                className="text-xs"
              >
                连接到 {targetNodeId}
              </Button>
            ))}
          </div>
        </div>
      )}

      {/* No Suggestions */}
      {(!suggestions || suggestions.length === 0) && (
        <div className="ml-8 text-sm text-gray-600">
          请手动添加连接到其他节点
        </div>
      )}
    </div>
  );
}
