'use client';

/**
 * ValidationStatusBadge Component
 *
 * 显示工作流验证状态徽章
 * 支持 5 种状态：valid, warning, error, validating, not_validated
 */

import { CheckCircle2, AlertTriangle, XCircle, Loader2, MinusCircle } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { cn } from '@/lib/utils';

export type ValidationStatus =
  | 'valid'
  | 'warning'
  | 'error'
  | 'validating'
  | 'not_validated';

interface ValidationStatusBadgeProps {
  status: ValidationStatus;
  errorCount?: number;
  warningCount?: number;
  className?: string;
}

const statusConfig: Record<
  ValidationStatus,
  {
    label: string;
    icon: typeof CheckCircle2;
    className: string;
  }
> = {
  valid: {
    label: '有效',
    icon: CheckCircle2,
    className: 'border-emerald-200 bg-emerald-50 text-emerald-700'
  },
  warning: {
    label: '警告',
    icon: AlertTriangle,
    className: 'border-yellow-200 bg-yellow-50 text-yellow-700'
  },
  error: {
    label: '错误',
    icon: XCircle,
    className: 'border-red-200 bg-red-50 text-red-700'
  },
  validating: {
    label: '验证中',
    icon: Loader2,
    className: 'border-blue-200 bg-blue-50 text-blue-700'
  },
  not_validated: {
    label: '未验证',
    icon: MinusCircle,
    className: 'border-gray-200 bg-gray-50 text-gray-700'
  }
};

export function ValidationStatusBadge({
  status,
  errorCount,
  warningCount,
  className
}: ValidationStatusBadgeProps) {
  const config = statusConfig[status];
  const Icon = config.icon;

  // 构建计数文本
  const countsText = [];
  if (errorCount !== undefined && errorCount > 0) {
    countsText.push(`${errorCount} 错误`);
  }
  if (warningCount !== undefined && warningCount > 0) {
    countsText.push(`${warningCount} 警告`);
  }

  return (
    <Badge
      data-testid={`validation-status-${status}`}
      className={cn(config.className, className)}
    >
      <Icon
        className={cn(
          'h-3.5 w-3.5',
          status === 'validating' && 'animate-spin'
        )}
      />
      <span>{config.label}</span>
      {countsText.length > 0 && (
        <span
          data-testid="validation-counts"
          className="ml-1 opacity-75"
        >
          ({countsText.join(', ')})
        </span>
      )}
    </Badge>
  );
}
