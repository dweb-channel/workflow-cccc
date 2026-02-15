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
      <div className="flex items-center gap-1 overflow-x-auto scrollbar-none">
        {loading ? (
          <span className="px-3 py-1 text-xs text-slate-400">加载中...</span>
        ) : error ? (
          <span className="px-3 py-1 text-xs text-red-400">
            加载失败{" "}
            <button className="underline hover:text-red-500" onClick={onRetryLoad}>重试</button>
          </span>
        ) : (
          workspaces.map((ws) => {
            const isActive = activeWorkspaceId === ws.id;
            return (
              <div
                key={ws.id}
                className={`group relative flex shrink-0 items-center gap-1.5 rounded-full px-3 py-1 text-xs cursor-pointer transition-all ${
                  isActive
                    ? "bg-cyan-500/10 text-cyan-400 ring-1 ring-cyan-500/30"
                    : "text-slate-400 hover:bg-slate-700/50 hover:text-slate-300"
                }`}
                onClick={() => onSelect(ws)}
              >
                <FolderGit2 className="h-3 w-3 shrink-0" />
                <span className="max-w-[120px] truncate font-medium">{ws.name}</span>
                <span className={`text-[10px] ${isActive ? "text-cyan-400" : "text-slate-500"}`}>{ws.job_count}</span>

                {/* Edit/Delete on hover */}
                {isActive && (
                  <div className="ml-0.5 flex gap-0.5 opacity-0 group-hover:opacity-100 transition-opacity">
                    <button
                      className="rounded-full p-0.5 hover:bg-cyan-500/20"
                      onClick={(e) => handleEdit(e, ws)}
                      title="编辑"
                    >
                      <Pencil className="h-2.5 w-2.5 text-cyan-400" />
                    </button>
                    <button
                      className="rounded-full p-0.5 hover:bg-red-500/20"
                      onClick={(e) => handleDelete(e, ws.id)}
                      title="删除"
                    >
                      <X className="h-2.5 w-2.5 text-red-400" />
                    </button>
                  </div>
                )}
              </div>
            );
          })
        )}

        {/* Create new workspace */}
        <button
          className="flex shrink-0 items-center gap-1 rounded-full px-2 py-1 text-xs text-slate-400 transition-colors hover:bg-slate-700/50 hover:text-slate-300"
          onClick={handleCreate}
          title="新建项目组"
        >
          <Plus className="h-3 w-3" />
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
