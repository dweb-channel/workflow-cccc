'use client';

/**
 * CircularDependencyErrorActionable / LoopDetectedInfo Component
 *
 * Displays loop detection results:
 * - CONTROLLED_LOOP (warning): Amber styling, shows condition exit info
 * - CIRCULAR_DEPENDENCY (error): Red styling, shows break cycle actions
 */

import { XCircle, AlertTriangle, ArrowRight } from 'lucide-react';
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
  const { message, context, severity } = error;
  const { cycle_path, has_condition_exit, condition_node_id, max_iterations } = context;

  const isWarning = severity === "warning" || has_condition_exit;

  // Identify breakable edges (all edges except the last back edge)
  const breakableEdges = cycle_path.slice(0, -1).map((node, idx) => ({
    source: node,
    target: cycle_path[idx + 1],
    isBackEdge: idx === cycle_path.length - 2
  }));

  const borderColor = isWarning ? "border-amber-200" : "border-red-200";
  const bgColor = isWarning ? "bg-amber-50" : "bg-red-50";
  const iconColor = isWarning ? "text-amber-600" : "text-red-600";
  const pathBorder = isWarning ? "border-amber-200" : "border-red-200";
  const arrowColor = isWarning ? "text-amber-500" : "text-red-500";
  const Icon = isWarning ? AlertTriangle : XCircle;

  return (
    <div
      data-testid="error-actionable-circular-dependency"
      className={`border ${borderColor} ${bgColor} rounded-lg p-4`}
    >
      {/* Header */}
      <div className="flex items-start gap-3 mb-3">
        <Icon className={`h-5 w-5 ${iconColor} flex-shrink-0 mt-0.5`} />
        <div className="flex-1">
          <h4 className="text-sm font-semibold text-gray-900">
            {isWarning ? "检测到受控循环" : "检测到循环依赖"}
          </h4>
          <p className="text-sm text-gray-700 mt-1">
            {message}
          </p>
        </div>
      </div>

      {/* Controlled loop info */}
      {isWarning && condition_node_id && (
        <div className="ml-8 mb-3 rounded border border-amber-200 bg-white p-3">
          <div className="flex items-center gap-2 text-sm">
            <span className="text-amber-600">🔀</span>
            <span className="text-gray-700">
              由 <code className="rounded bg-amber-100 px-1.5 py-0.5 font-mono text-xs text-amber-800">{condition_node_id}</code> 控制退出
            </span>
          </div>
          {max_iterations != null && (
            <p className="mt-1 text-xs text-gray-500">
              最大迭代次数: {max_iterations}
            </p>
          )}
        </div>
      )}

      {/* Cycle Path Visualization */}
      <div className="ml-8 mb-3">
        <p className="text-sm font-medium text-gray-700 mb-2">
          循环路径 ({cycle_path.length} 个节点):
        </p>
        <div
          data-testid="cycle-path-visualization"
          className={`bg-white rounded border ${pathBorder} p-3`}
        >
          <div className="flex flex-wrap items-center gap-2">
            {cycle_path.map((nodeId, idx) => (
              <div key={idx} className="flex items-center gap-2">
                <code
                  data-testid={`cycle-node-${idx}`}
                  className={`px-2 py-1 rounded font-mono text-xs ${
                    nodeId === condition_node_id
                      ? 'bg-amber-200 text-amber-900 font-bold'
                      : idx === 0
                        ? isWarning
                          ? 'bg-amber-100 text-amber-800 font-bold'
                          : 'bg-red-200 text-red-900 font-bold'
                        : 'bg-gray-100 text-gray-800'
                  }`}
                >
                  {nodeId}
                </code>
                {idx < cycle_path.length - 1 && (
                  <ArrowRight className={`h-4 w-4 ${arrowColor}`} />
                )}
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Break Cycle Actions (only for errors, not warnings) */}
      {!isWarning && (
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
      )}
    </div>
  );
}
