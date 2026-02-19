"use client";

import { useState, useCallback } from "react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

// Types matching backend API
export interface TemplateListItem {
  name: string;
  title: string;
  description: string;
  icon?: string;
}

export interface TemplateDetail {
  name: string;
  title: string;
  nodes: Array<{
    id: string;
    type: string;
    position: { x: number; y: number };
    data?: Record<string, unknown>;
    config?: Record<string, unknown>;
  }>;
  edges: Array<{
    id: string;
    source: string;
    target: string;
    data?: Record<string, unknown>;
  }>;
}

interface TemplateSelectorProps {
  onSelectTemplate: (template: TemplateDetail) => void;
  disabled?: boolean;
}

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export function TemplateSelector({ onSelectTemplate, disabled }: TemplateSelectorProps) {
  const [open, setOpen] = useState(false);
  const [templates, setTemplates] = useState<TemplateListItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selecting, setSelecting] = useState<string | null>(null);

  // Confirmation dialog state
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [pendingTemplate, setPendingTemplate] = useState<TemplateDetail | null>(null);

  const fetchTemplates = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/api/v2/templates`);
      if (!res.ok) {
        throw new Error(`加载模板列表失败: ${res.status}`);
      }
      const data = await res.json();
      setTemplates(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "加载模板列表失败");
    } finally {
      setLoading(false);
    }
  }, []);

  const handleOpenChange = useCallback((isOpen: boolean) => {
    setOpen(isOpen);
    if (isOpen) {
      fetchTemplates();
    } else {
      setError(null);
    }
  }, [fetchTemplates]);

  const handleSelectTemplate = useCallback(async (name: string) => {
    setSelecting(name);
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/api/v2/templates/${name}`);
      if (!res.ok) {
        if (res.status === 404) {
          throw new Error("模板不存在");
        }
        throw new Error(`加载模板失败: ${res.status}`);
      }
      const template: TemplateDetail = await res.json();

      // Show confirmation dialog instead of native confirm
      setPendingTemplate(template);
      setConfirmOpen(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "加载模板失败");
    } finally {
      setSelecting(null);
    }
  }, []);

  const handleConfirmApply = useCallback(() => {
    if (pendingTemplate) {
      onSelectTemplate(pendingTemplate);
      setConfirmOpen(false);
      setOpen(false);
      setPendingTemplate(null);
    }
  }, [pendingTemplate, onSelectTemplate]);

  const handleCancelApply = useCallback(() => {
    setConfirmOpen(false);
    setPendingTemplate(null);
  }, []);

  return (
    <>
      <Dialog open={open} onOpenChange={handleOpenChange}>
        <DialogTrigger asChild>
          <Button
            variant="secondary"
            size="sm"
            className="w-full text-xs"
            disabled={disabled}
          >
            从模板创建
          </Button>
        </DialogTrigger>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>选择工作流模板</DialogTitle>
            <DialogDescription>
              选择一个预置模板快速开始，模板将覆盖当前画布内容
            </DialogDescription>
          </DialogHeader>

          <div className="mt-4">
            {loading && (
              <div className="flex items-center justify-center py-8">
                <span className="text-sm text-muted-foreground">加载中...</span>
              </div>
            )}

            {error && (
              <div className="rounded-lg border border-destructive/30 bg-destructive/10 p-4 text-sm text-destructive">
                {error}
              </div>
            )}

            {!loading && !error && templates.length === 0 && (
              <div className="flex items-center justify-center py-8">
                <span className="text-sm text-muted-foreground">暂无可用模板</span>
              </div>
            )}

            {!loading && !error && templates.length > 0 && (
              <div className="grid gap-3 sm:grid-cols-2">
                {templates.map((template) => (
                  <Card
                    key={template.name}
                    className={`cursor-pointer transition-colors hover:border-primary/50 hover:bg-primary/5 ${
                      selecting === template.name ? "border-primary bg-primary/5" : ""
                    }`}
                    onClick={() => handleSelectTemplate(template.name)}
                  >
                    <CardHeader className="pb-2">
                      <CardTitle className="flex items-center gap-2 text-base">
                        {template.icon && <span>{template.icon}</span>}
                        {template.title}
                      </CardTitle>
                    </CardHeader>
                    <CardContent>
                      <p className="text-xs text-muted-foreground">
                        {template.description}
                      </p>
                      {selecting === template.name && (
                        <span className="mt-2 block text-xs text-primary">加载中...</span>
                      )}
                    </CardContent>
                  </Card>
                ))}
              </div>
            )}
          </div>
        </DialogContent>
      </Dialog>

      {/* Confirmation Dialog */}
      <Dialog open={confirmOpen} onOpenChange={setConfirmOpen}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>确认使用模板</DialogTitle>
            <DialogDescription>
              确定使用模板"{pendingTemplate?.title}"？这将覆盖当前画布内容。
            </DialogDescription>
          </DialogHeader>
          <DialogFooter className="gap-2 sm:gap-0">
            <Button variant="ghost" onClick={handleCancelApply}>
              取消
            </Button>
            <Button onClick={handleConfirmApply}>
              确认使用
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
