"use client";

import { useState, useEffect } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
  DialogDescription,
} from "@/components/ui/dialog";
import { DirectoryPicker } from "./DirectoryPicker";
import type { Workspace } from "@/lib/api";

interface WorkspaceDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** If provided, dialog is in edit mode */
  workspace?: Workspace | null;
  onCreate: (name: string, repoPath: string) => Promise<unknown>;
  onUpdate?: (id: string, name: string) => Promise<unknown>;
}

export function WorkspaceDialog({
  open,
  onOpenChange,
  workspace,
  onCreate,
  onUpdate,
}: WorkspaceDialogProps) {
  const isEdit = !!workspace;
  const [name, setName] = useState("");
  const [repoPath, setRepoPath] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (open) {
      setName(workspace?.name ?? "");
      setRepoPath(workspace?.repo_path ?? "");
    }
  }, [open, workspace]);

  const handleSave = async () => {
    if (!name.trim()) return;
    setSaving(true);
    try {
      if (isEdit && onUpdate) {
        await onUpdate(workspace.id, name.trim());
      } else {
        if (!repoPath.trim()) return;
        await onCreate(name.trim(), repoPath.trim());
      }
      onOpenChange(false);
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[480px]">
        <DialogHeader>
          <DialogTitle>{isEdit ? "编辑项目组" : "新建项目组"}</DialogTitle>
          <DialogDescription>
            {isEdit
              ? "修改项目组名称"
              : "选择一个仓库目录，创建项目组后可快速启动批量修复"}
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4 py-2">
          <div className="space-y-2">
            <Label htmlFor="ws-name">项目组名称</Label>
            <Input
              id="ws-name"
              placeholder="如 pixcheese-preview"
              value={name}
              onChange={(e) => setName(e.target.value)}
              autoFocus
            />
          </div>

          {!isEdit && (
            <div className="space-y-2">
              <Label>仓库路径</Label>
              <DirectoryPicker value={repoPath} onChange={setRepoPath} />
              <p className="text-xs text-slate-400">
                该仓库将绑定到此项目组，后续创建任务时自动使用
              </p>
            </div>
          )}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            取消
          </Button>
          <Button
            onClick={handleSave}
            disabled={saving || !name.trim() || (!isEdit && !repoPath.trim())}
          >
            {saving ? "保存中..." : isEdit ? "保存" : "创建"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
