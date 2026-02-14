"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Plus, FolderGit2, Pencil, X } from "lucide-react";
import type { Workspace } from "@/lib/api";
import { WorkspaceDialog } from "./WorkspaceDialog";

interface WorkspaceTabsProps {
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

export function WorkspaceTabs({
  workspaces,
  activeWorkspaceId,
  loading,
  error,
  onSelect,
  onCreate,
  onUpdate,
  onDelete,
  onRetryLoad,
}: WorkspaceTabsProps) {
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
    <>
      <div className="flex items-center gap-1 overflow-x-auto pb-px scrollbar-none">
        {loading ? (
          <span className="px-3 py-1.5 text-xs text-slate-400">加载中...</span>
        ) : error ? (
          <span className="px-3 py-1.5 text-xs text-red-400">
            加载失败{" "}
            <button className="underline hover:text-red-500" onClick={onRetryLoad}>重试</button>
          </span>
        ) : (
          workspaces.map((ws) => {
            const isActive = activeWorkspaceId === ws.id;
            return (
              <div
                key={ws.id}
                className={`group relative flex shrink-0 items-center gap-1.5 rounded-t-lg px-3 py-2 text-sm cursor-pointer transition-all ${
                  isActive
                    ? "bg-white text-slate-900 shadow-sm"
                    : "text-slate-500 hover:bg-slate-100 hover:text-slate-700"
                }`}
                onClick={() => onSelect(ws)}
              >
                <FolderGit2 className="h-3.5 w-3.5 shrink-0" />
                <span className="max-w-[120px] truncate font-medium">{ws.name}</span>
                <span className="text-[10px] text-slate-400">{ws.job_count}</span>

                {/* Edit/Delete on hover */}
                {isActive && (
                  <div className="ml-1 flex gap-0.5 opacity-0 group-hover:opacity-100 transition-opacity">
                    <button
                      className="rounded p-0.5 hover:bg-slate-200"
                      onClick={(e) => handleEdit(e, ws)}
                      title="编辑"
                    >
                      <Pencil className="h-2.5 w-2.5 text-slate-400" />
                    </button>
                    <button
                      className="rounded p-0.5 hover:bg-red-100"
                      onClick={(e) => handleDelete(e, ws.id)}
                      title="删除"
                    >
                      <X className="h-2.5 w-2.5 text-slate-400" />
                    </button>
                  </div>
                )}
              </div>
            );
          })
        )}

        {/* Create new workspace tab */}
        <button
          className="flex shrink-0 items-center gap-1 rounded-lg px-2 py-1.5 text-xs text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-600"
          onClick={handleCreate}
          title="新建项目组"
        >
          <Plus className="h-3.5 w-3.5" />
        </button>
      </div>

      <WorkspaceDialog
        open={dialogOpen}
        onOpenChange={setDialogOpen}
        workspace={editingWorkspace}
        onCreate={onCreate}
        onUpdate={onUpdate}
      />
    </>
  );
}
