"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import { confirmWorkflow } from "@/lib/api";

interface WorkflowConfirmDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  workflowId: string;
  runId: string;
  stage: "initial" | "final";
  onConfirmed?: () => void;
}

export function WorkflowConfirmDialog({
  open,
  onOpenChange,
  workflowId,
  runId,
  stage,
  onConfirmed,
}: WorkflowConfirmDialogProps) {
  const [feedback, setFeedback] = useState("");
  const [loading, setLoading] = useState(false);

  const isInitial = stage === "initial";
  const title = isInitial ? "工作流确认" : "最终确认";
  const subtitle = isInitial
    ? "初始确认阶段 - 请审核并确认是否继续执行"
    : "最终确认阶段 - 确认后工作流将完成执行";
  const confirmText = isInitial ? "确认" : "完成";
  const confirmColor = isInitial
    ? "bg-emerald-500 hover:bg-emerald-600"
    : "bg-blue-500 hover:bg-blue-600";

  const handleConfirm = async (approved: boolean) => {
    setLoading(true);
    try {
      await confirmWorkflow(workflowId, runId, {
        stage,
        approved,
        feedback,
      });
      onOpenChange(false);
      setFeedback("");
      onConfirmed?.();
    } catch (err) {
      alert(err instanceof Error ? err.message : "操作失败");
    } finally {
      setLoading(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-[480px] rounded-[20px] p-8">
        <DialogHeader className="gap-2">
          <DialogTitle className="text-2xl font-normal text-slate-900">
            {title}
          </DialogTitle>
          <DialogDescription className="text-sm text-slate-500">
            {subtitle}
          </DialogDescription>
        </DialogHeader>

        <div className="my-4 h-px bg-slate-200" />

        <div className="space-y-4">
          <div className="space-y-2">
            <Label className="text-sm text-slate-700">反馈意见（可选）</Label>
            <Textarea
              placeholder="输入您的反馈意见..."
              value={feedback}
              onChange={(e) => setFeedback(e.target.value)}
              className="min-h-[100px] resize-none rounded-xl border-0 bg-slate-50"
            />
          </div>
        </div>

        <div className="mt-6 flex gap-4">
          <Button
            variant="secondary"
            onClick={() => handleConfirm(false)}
            disabled={loading}
            className="flex-1 rounded-xl bg-white py-3 text-red-500 shadow-sm hover:bg-slate-50 hover:text-red-600"
          >
            拒绝
          </Button>
          <Button
            onClick={() => handleConfirm(true)}
            disabled={loading}
            className={`flex-1 rounded-xl py-3 text-white ${confirmColor}`}
          >
            {loading ? "处理中..." : confirmText}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
