"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Plus, FolderGit2, Pencil, Trash2 } from "lucide-react";
import type { Workspace } from "@/lib/api";
import { WorkspaceDialog } from "./WorkspaceDialog";

interface WorkspacePanelProps {
  workspaces: Workspace[];
  activeWorkspaceId: string | null;
  loading: boolean;
  error: string | null;
  onSelect: (ws: Workspace) => void;
  onCreate: (name: string, repoPath: string) => Promise<unknown>;
  onUpdate: (id: string, name: string) => Promise<unknown>;
  onDelete: (id: string) => Promise<unknown>;
  onRetryLoad: () => void;
}

export function WorkspacePanel({
  workspaces,
  activeWorkspaceId,
  loading,
  error,
  onSelect,
  onCreate,
  onUpdate,
  onDelete,
  onRetryLoad,
}: WorkspacePanelProps) {
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editingWorkspace, setEditingWorkspace] = useState<Workspace | null>(null);

  const handleEdit = (e: React.MouseEvent, ws: Workspace) => {
    e.stopPropagation();
    setEditingWorkspace(ws);
    setDialogOpen(true);
  };

  const handleDelete = (e: React.MouseEvent, id: string) => {
    e.stopPropagation();
    onDelete(id);
  };

  const handleCreate = () => {
    setEditingWorkspace(null);
    setDialogOpen(true);
  };

  return (
    <div className="flex w-[220px] shrink-0 flex-col border-r border-slate-200 bg-white">
      <div className="flex items-center justify-between px-3 py-3 border-b border-slate-100">
        <span className="text-xs font-semibold text-slate-500 uppercase tracking-wider">
          项目组
        </span>
        <Button
          variant="ghost"
          size="sm"
          className="h-6 w-6 p-0"
          onClick={handleCreate}
        >
          <Plus className="h-3.5 w-3.5" />
        </Button>
      </div>

      <div className="flex-1 overflow-y-auto py-1">
        {loading ? (
          <div className="px-3 py-4 text-xs text-slate-400 text-center">
            加载中...
          </div>
        ) : error ? (
          <div className="px-3 py-6 text-center">
            <p className="text-sm text-red-500 mb-2">加载失败</p>
            <p className="text-xs text-slate-400 mb-3">{error}</p>
            <Button size="sm" variant="outline" onClick={onRetryLoad}>
              重试
            </Button>
          </div>
        ) : workspaces.length === 0 ? (
          <div className="px-3 py-8 text-center">
            <FolderGit2 className="mx-auto h-8 w-8 text-slate-300 mb-2" />
            <p className="text-sm text-slate-500 mb-1">还没有项目组</p>
            <p className="text-xs text-slate-400 mb-3">
              创建一个项目组来开始
            </p>
            <Button size="sm" variant="outline" onClick={handleCreate}>
              <Plus className="mr-1.5 h-3 w-3" />
              新建项目组
            </Button>
          </div>
        ) : (
          workspaces.map((ws) => (
            <div
              key={ws.id}
              className={`group flex items-center gap-2 px-3 py-2 mx-1 rounded-md cursor-pointer transition-colors ${
                activeWorkspaceId === ws.id
                  ? "bg-blue-50 text-blue-700"
                  : "text-slate-600 hover:bg-slate-50"
              }`}
              onClick={() => onSelect(ws)}
            >
              <FolderGit2 className="h-3.5 w-3.5 shrink-0" />
              <div className="flex-1 min-w-0">
                <div className="text-sm font-medium truncate">{ws.name}</div>
                <div className="text-[10px] text-slate-400 truncate">
                  {ws.job_count} 个任务
                </div>
              </div>
              <div className="flex gap-0.5 opacity-0 group-hover:opacity-100 transition-opacity shrink-0">
                <button
                  className="p-1 rounded hover:bg-slate-200"
                  onClick={(e) => handleEdit(e, ws)}
                  title="编辑"
                >
                  <Pencil className="h-3 w-3" />
                </button>
                <button
                  className="p-1 rounded hover:bg-red-100 text-red-500"
                  onClick={(e) => handleDelete(e, ws.id)}
                  title="删除"
                >
                  <Trash2 className="h-3 w-3" />
                </button>
              </div>
            </div>
          ))
        )}
      </div>

      <WorkspaceDialog
        open={dialogOpen}
        onOpenChange={setDialogOpen}
        workspace={editingWorkspace}
        onCreate={onCreate}
        onUpdate={onUpdate}
      />
    </div>
  );
}
