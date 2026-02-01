"use client";

import { Button } from "@/components/ui/button";

export type EditorMode = "view" | "edit";

interface EditorToolbarProps {
  mode: EditorMode;
  onModeChange: (mode: EditorMode) => void;
  onSaveGraph: () => void;
  saving: boolean;
  hasChanges: boolean;
}

export function EditorToolbar({
  mode,
  onModeChange,
  onSaveGraph,
  saving,
  hasChanges,
}: EditorToolbarProps) {
  return (
    <div className="flex items-center gap-2">
      {/* Mode toggle */}
      <div className="flex rounded-md border border-slate-200">
        <button
          onClick={() => onModeChange("view")}
          className={`px-3 py-1 text-xs font-medium transition-colors ${
            mode === "view"
              ? "bg-slate-800 text-white"
              : "bg-white text-slate-600 hover:bg-slate-50"
          } rounded-l-md`}
        >
          查看
        </button>
        <button
          onClick={() => onModeChange("edit")}
          className={`px-3 py-1 text-xs font-medium transition-colors ${
            mode === "edit"
              ? "bg-blue-600 text-white"
              : "bg-white text-slate-600 hover:bg-slate-50"
          } rounded-r-md`}
        >
          编辑
        </button>
      </div>

      {/* Save button (edit mode only) */}
      {mode === "edit" && (
        <Button
          size="sm"
          variant="secondary"
          onClick={onSaveGraph}
          disabled={saving || !hasChanges}
          className="text-xs"
        >
          {saving ? "保存中..." : hasChanges ? "保存图" : "已保存"}
        </Button>
      )}
    </div>
  );
}
