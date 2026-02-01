'use client';

/**
 * JumpReferenceWarningActionable Component
 *
 * 显示条件节点的跳转引用警告，可视化跳转路径
 * 用于 conditional 节点的分支跳转验证
 */

import { AlertCircle, ArrowRight } from 'lucide-react';
import { Button } from '@/components/ui/button';
import type { ValidationWarning } from '@/lib/validation';

interface JumpReferenceWarningActionableProps {
  warning: ValidationWarning;
  onFixJumpTarget?: (nodeId: string, jumpTargetId: string) => void;
}

interface JumpPath {
  condition: string;
  target: string;
  exists: boolean;
}

export function JumpReferenceWarningActionable({
  warning,
  onFixJumpTarget
}: JumpReferenceWarningActionableProps) {
  const { node_ids, message, context } = warning;
  const nodeId = node_ids[0]; // 单个节点警告

  // 从 context 提取跳转路径信息
  const jumpPaths: JumpPath[] = [];
  if (context && typeof context === 'object') {
    const ctx = context as any;
    if (ctx.jump_paths && Array.isArray(ctx.jump_paths)) {
      jumpPaths.push(...ctx.jump_paths);
    }
  }

  return (
    <div
      data-testid="warning-actionable-jump-reference"
      className="border border-yellow-200 bg-yellow-50 rounded-lg p-4"
    >
      {/* Header */}
      <div className="flex items-start gap-3 mb-3">
        <AlertCircle className="h-5 w-5 text-yellow-600 flex-shrink-0 mt-0.5" />
        <div className="flex-1">
          <h4 className="text-sm font-semibold text-gray-900">
            跳转引用警告
          </h4>
          <p className="text-sm text-gray-700 mt-1">
            {message}
          </p>
          <p className="text-xs text-gray-600 mt-1">
            节点 ID: <code className="bg-yellow-100 px-1 rounded">{nodeId}</code>
          </p>
        </div>
      </div>

      {/* Jump Paths Visualization */}
      {jumpPaths.length > 0 && (
        <div className="ml-8 mb-3">
          <p className="text-sm font-medium text-gray-700 mb-2">
            跳转路径 ({jumpPaths.length} 个分支):
          </p>
          <div
            data-testid="jump-paths-list"
            className="bg-white rounded border border-yellow-200 divide-y divide-yellow-100"
          >
            {jumpPaths.map((path, idx) => (
              <div
                key={idx}
                data-testid={`jump-path-${idx}`}
                className="p-3"
              >
                <div className="flex items-center gap-2 mb-2">
                  <code className="text-xs font-mono bg-yellow-100 text-yellow-800 px-2 py-1 rounded">
                    {path.condition}
                  </code>
                  <ArrowRight className="h-4 w-4 text-gray-400" />
                  <code
                    className={`text-xs font-mono px-2 py-1 rounded ${
                      path.exists
                        ? 'bg-green-100 text-green-800'
                        : 'bg-red-100 text-red-800'
                    }`}
                  >
                    {path.target}
                  </code>
                  {!path.exists && (
                    <span className="text-xs text-red-600">(目标不存在)</span>
                  )}
                </div>
                {!path.exists && (
                  <div className="ml-6">
                    <Button
                      data-testid={`fix-jump-${path.target}`}
                      variant="secondary"
                      size="sm"
                      onClick={() => onFixJumpTarget?.(nodeId, path.target)}
                      className="text-xs"
                    >
                      修正跳转目标
                    </Button>
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Generic message when no jump paths */}
      {jumpPaths.length === 0 && (
        <div className="ml-8 text-sm text-gray-600">
          请检查条件节点的跳转配置
        </div>
      )}
    </div>
  );
}
