'use client';

/**
 * MissingFieldReferenceErrorActionable Component
 *
 * 显示字段引用错误，提供可用字段选择器
 * 基于 Context 字段契约：field, available_fields, upstream_node_ids 保证非空
 */

import { XCircle } from 'lucide-react';
import { Button } from '@/components/ui/button';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from '@/components/ui/select';
import type { ValidationError, MissingFieldReferenceContext } from '@/lib/validation';
import { useState } from 'react';

interface MissingFieldReferenceErrorActionableProps {
  error: ValidationError & { context: MissingFieldReferenceContext };
  onFixField?: (nodeId: string, oldField: string, newField: string) => void;
}

export function MissingFieldReferenceErrorActionable({
  error,
  onFixField
}: MissingFieldReferenceErrorActionableProps) {
  const { node_ids, message, context } = error;
  const nodeId = node_ids[0]; // 单个节点错误
  const { field, available_fields, upstream_node_ids } = context;

  const [selectedField, setSelectedField] = useState<string>('');

  const handleFix = () => {
    if (selectedField) {
      onFixField?.(nodeId, field, selectedField);
    }
  };

  return (
    <div
      data-testid="error-actionable-missing-field-reference"
      className="border border-red-800 bg-red-950 rounded-lg p-4"
    >
      {/* Header */}
      <div className="flex items-start gap-3 mb-3">
        <XCircle className="h-5 w-5 text-red-600 flex-shrink-0 mt-0.5" />
        <div className="flex-1">
          <h4 className="text-sm font-semibold text-white">
            字段引用错误
          </h4>
          <p className="text-sm text-muted-foreground mt-1">
            {message}
          </p>
          <p className="text-xs text-muted-foreground mt-1">
            节点 ID: <code className="bg-red-900/50 px-1 rounded">{nodeId}</code>
          </p>
        </div>
      </div>

      {/* Error Details */}
      <div className="ml-8 mb-3">
        <div className="bg-card rounded border border-red-800 p-3 space-y-2">
          <div className="flex items-center gap-2 text-sm">
            <span className="text-muted-foreground">引用字段:</span>
            <code
              data-testid="missing-field-name"
              className="bg-red-900/50 text-red-300 px-2 py-0.5 rounded font-mono text-xs"
            >
              {field}
            </code>
          </div>
          <div className="text-xs text-muted-foreground">
            上游节点: {upstream_node_ids?.join(', ') ?? '无'}
          </div>
        </div>
      </div>

      {/* Field Picker */}
      <div className="ml-8 space-y-2">
        <p className="text-sm font-medium text-muted-foreground">
          选择可用字段 ({available_fields.length} 个可用):
        </p>
        <div
          data-testid="available-fields-picker"
          className="flex gap-2 items-center"
        >
          <Select value={selectedField} onValueChange={setSelectedField}>
            <SelectTrigger className="w-64">
              <SelectValue placeholder="选择替换字段..." />
            </SelectTrigger>
            <SelectContent>
              {available_fields.map((availableField) => (
                <SelectItem
                  key={availableField}
                  value={availableField}
                  data-testid={`field-option-${availableField}`}
                >
                  {availableField}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Button
            data-testid="apply-field-fix"
            onClick={handleFix}
            disabled={!selectedField}
            size="sm"
          >
            应用修复
          </Button>
        </div>
      </div>
    </div>
  );
}
