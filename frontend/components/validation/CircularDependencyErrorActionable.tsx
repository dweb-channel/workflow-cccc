'use client';

/**
 * CircularDependencyErrorActionable Component
 *
 * 显示循环依赖错误，可视化循环路径
 * 基于 Context 字段契约：cycle_path 保证至少 3 个节点
 */

import { XCircle, ArrowRight } from 'lucide-react';
import { Button } from '@/components/ui/button';
import type { ValidationError, CircularDependencyContext } from '@/lib/validation';

interface CircularDependencyErrorActionableProps {
  error: ValidationError & { context: CircularDependencyContext };
  onBreakCycle?: (sourceNode: string, targetNode: string) => void;
}

export function CircularDependencyErrorActionable({
  error,
  onBreakCycle
}: CircularDependencyErrorActionableProps) {
  const { message, context } = error;
  const { cycle_path } = context;

  // 识别可打断的边（除了最后一个回环边，任何边都可以打断）
  const breakableEdges = cycle_path.slice(0, -1).map((node, idx) => ({
    source: node,
    target: cycle_path[idx + 1],
    isBackEdge: idx === cycle_path.length - 2
  }));

  return (
    <div
      data-testid="error-actionable-circular-dependency"
      className="border border-red-200 bg-red-50 rounded-lg p-4"
    >
      {/* Header */}
      <div className="flex items-start gap-3 mb-3">
        <XCircle className="h-5 w-5 text-red-600 flex-shrink-0 mt-0.5" />
        <div className="flex-1">
          <h4 className="text-sm font-semibold text-gray-900">
            检测到循环依赖
          </h4>
          <p className="text-sm text-gray-700 mt-1">
            {message}
          </p>
        </div>
      </div>

      {/* Cycle Path Visualization */}
      <div className="ml-8 mb-3">
        <p className="text-sm font-medium text-gray-700 mb-2">
          循环路径 ({cycle_path.length} 个节点):
        </p>
        <div
          data-testid="cycle-path-visualization"
          className="bg-white rounded border border-red-200 p-3"
        >
          <div className="flex flex-wrap items-center gap-2">
            {cycle_path.map((nodeId, idx) => (
              <div key={idx} className="flex items-center gap-2">
                <code
                  data-testid={`cycle-node-${idx}`}
                  className={`px-2 py-1 rounded font-mono text-xs ${
                    idx === 0
                      ? 'bg-red-200 text-red-900 font-bold'
                      : 'bg-gray-100 text-gray-800'
                  }`}
                >
                  {nodeId}
                </code>
                {idx < cycle_path.length - 1 && (
                  <ArrowRight className="h-4 w-4 text-red-500" />
                )}
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Break Cycle Actions */}
      <div className="ml-8 space-y-2">
        <p className="text-sm font-medium text-gray-700">
          打断循环 (删除以下任一连接):
        </p>
        <div
          data-testid="break-cycle-actions"
          className="space-y-1"
        >
          {breakableEdges.map((edge, idx) => (
            <div
              key={idx}
              className="flex items-center gap-2 text-sm"
            >
              <Button
                data-testid={`break-edge-${edge.source}-${edge.target}`}
                variant="secondary"
                size="sm"
                onClick={() => onBreakCycle?.(edge.source, edge.target)}
                className="text-xs"
              >
                删除连接
              </Button>
              <span className="text-gray-700">
                {edge.source} → {edge.target}
                {edge.isBackEdge && (
                  <span className="ml-2 text-red-600 text-xs">(回环边)</span>
                )}
              </span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
