"use client";

import { Button } from "@/components/ui/button";
import { TemplateSelector, type TemplateDetail } from "@/components/workflow-editor/TemplateSelector";
import type { V2WorkflowResponse } from "@/lib/api";

const STATUS_MAP: Record<string, { label: string; color: string }> = {
  draft: { label: "草稿", color: "bg-muted-foreground" },
  published: { label: "已发布", color: "bg-blue-500" },
  archived: { label: "已归档", color: "bg-muted-foreground" },
  running: { label: "运行中", color: "bg-emerald-500" },
  success: { label: "成功", color: "bg-green-500" },
  failed: { label: "失败", color: "bg-red-500" },
};

function formatRelativeTime(isoString: string): string {
  try {
    const date = new Date(isoString);
    const now = new Date();
    const diffMs = now.getTime() - date.getTime();
    const diffMins = Math.floor(diffMs / 60000);
    if (diffMins < 1) return "刚刚";
    if (diffMins < 60) return `${diffMins} 分钟前`;
    const diffHours = Math.floor(diffMins / 60);
    if (diffHours < 24) return `${diffHours} 小时前`;
    return date.toLocaleDateString("zh-CN");
  } catch {
    return isoString;
  }
}

interface WorkflowSidebarProps {
  workflowList: V2WorkflowResponse[];
  currentWorkflowId: string | undefined;
  creating: boolean;
  running: boolean;
  workflow: V2WorkflowResponse | null;
  renamingId: string | null;
  renameValue: string;
  setRenameValue: (v: string) => void;
  setRenamingId: (id: string | null) => void;
  onCreateWorkflow: () => void;
  onSwitchWorkflow: (id: string) => void;
  onStartRename: (wf: V2WorkflowResponse, e: React.MouseEvent) => void;
  onConfirmRename: (id: string) => void;
  onDeleteWorkflow: (id: string) => void;
  onApplyTemplate: (template: TemplateDetail) => void;
}

export function WorkflowSidebar({
  workflowList,
  currentWorkflowId,
  creating,
  running,
  workflow,
  renamingId,
  renameValue,
  setRenameValue,
  setRenamingId,
  onCreateWorkflow,
  onSwitchWorkflow,
  onStartRename,
  onConfirmRename,
  onDeleteWorkflow,
  onApplyTemplate,
}: WorkflowSidebarProps) {
  return (
    <div className="w-[200px] shrink-0 border-r border-border bg-card/50 overflow-y-auto p-4">
      <div className="space-y-2">
        <div className="flex items-center justify-between">
          <h2 className="text-xs font-medium text-muted-foreground">工作流列表</h2>
          <Button
            variant="ghost"
            size="sm"
            className="h-6 w-6 p-0 text-base"
            onClick={onCreateWorkflow}
            disabled={creating}
          >
            {creating ? "…" : "+"}
          </Button>
        </div>
        <div className="space-y-1">
          {workflowList.length === 0 ? (
            <p className="py-4 text-center text-xs text-muted-foreground">暂无工作流，点击 + 创建</p>
          ) : (
            workflowList.map((wf) => {
              const active = wf.id === currentWorkflowId;
              const wfStatus = STATUS_MAP[wf.status] || { label: wf.status, color: "bg-muted-foreground" };
              return (
                <div
                  key={wf.id}
                  className={`group cursor-pointer rounded-lg px-3 py-2 transition-colors ${
                    active ? "bg-muted/50 ring-1 ring-primary/30" : "hover:bg-muted/30"
                  }`}
                  onClick={() => onSwitchWorkflow(wf.id)}
                  onDoubleClick={(e) => onStartRename(wf, e)}
                >
                  <div className="flex items-center justify-between">
                    {renamingId === wf.id ? (
                      <input
                        className="w-full rounded border border-primary/50 bg-input-bg px-1 py-0.5 text-sm text-foreground outline-none focus:ring-1 focus:ring-primary"
                        value={renameValue}
                        onChange={(e) => setRenameValue(e.target.value)}
                        onBlur={() => onConfirmRename(wf.id)}
                        onKeyDown={(e) => {
                          if (e.key === "Enter") onConfirmRename(wf.id);
                          if (e.key === "Escape") setRenamingId(null);
                        }}
                        onClick={(e) => e.stopPropagation()}
                        autoFocus
                      />
                    ) : (
                      <span className={`truncate text-sm ${active ? "font-medium text-foreground" : "text-muted-foreground"}`}>
                        {wf.name}
                      </span>
                    )}
                    {renamingId !== wf.id && (
                      <button
                        className="ml-1 hidden shrink-0 rounded p-0.5 text-muted-foreground hover:bg-destructive/10 hover:text-destructive group-hover:block"
                        onClick={(e) => { e.stopPropagation(); onDeleteWorkflow(wf.id); }}
                        title="删除"
                      >
                        ✕
                      </button>
                    )}
                  </div>
                  <div className="mt-0.5 flex items-center gap-1.5">
                    <span className={`inline-block h-1.5 w-1.5 rounded-full ${wfStatus.color}`} />
                    <span className="text-[10px] text-muted-foreground">{wfStatus.label}</span>
                    <span className="text-[10px] text-muted-foreground/70">·</span>
                    <span className="text-[10px] text-muted-foreground">{formatRelativeTime(wf.updated_at)}</span>
                  </div>
                </div>
              );
            })
          )}
        </div>
      </div>
      {/* Template Selector */}
      <div className="mt-4 border-t border-border pt-4">
        <TemplateSelector
          onSelectTemplate={onApplyTemplate}
          disabled={!workflow || running}
        />
      </div>
    </div>
  );
}
