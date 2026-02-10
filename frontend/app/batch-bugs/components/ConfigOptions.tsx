"use client";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type { ValidationLevel, FailurePolicy } from "../types";

interface ConfigOptionsProps {
  validationLevel: ValidationLevel;
  failurePolicy: FailurePolicy;
  onValidationLevelChange: (level: ValidationLevel) => void;
  onFailurePolicyChange: (policy: FailurePolicy) => void;
}

export function ConfigOptions({
  validationLevel,
  failurePolicy,
  onValidationLevelChange,
  onFailurePolicyChange,
}: ConfigOptionsProps) {
  return (
    <Card>
      <CardHeader className="py-3">
        <CardTitle className="text-sm">配置选项</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="space-y-2">
          <Label className="text-xs">验证级别</Label>
          <Select
            value={validationLevel}
            onValueChange={(v) =>
              onValidationLevelChange(v as ValidationLevel)
            }
          >
            <SelectTrigger>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="minimal">快速验证 (lint only)</SelectItem>
              <SelectItem value="standard">
                标准验证 (lint + 单元测试)
              </SelectItem>
              <SelectItem value="thorough">
                完整验证 (lint + 单元 + E2E)
              </SelectItem>
            </SelectContent>
          </Select>
        </div>

        <div className="space-y-2">
          <Label className="text-xs">失败策略</Label>
          <Select
            value={failurePolicy}
            onValueChange={(v) =>
              onFailurePolicyChange(v as FailurePolicy)
            }
          >
            <SelectTrigger>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="skip">跳过继续 (推荐)</SelectItem>
              <SelectItem value="stop">停止等待</SelectItem>
              <SelectItem value="retry">自动重试</SelectItem>
            </SelectContent>
          </Select>
        </div>
      </CardContent>
    </Card>
  );
}
