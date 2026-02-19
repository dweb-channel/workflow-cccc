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
      <div className="flex rounded-md border border-border">
        <button
          onClick={() => onModeChange("view")}
          className={`px-3 py-1 text-xs font-medium transition-colors ${
            mode === "view"
              ? "bg-primary text-primary-foreground"
              : "bg-muted text-muted-foreground hover:bg-muted/80"
          } rounded-l-md`}
        >
          查看
        </button>
        <button
          onClick={() => onModeChange("edit")}
          className={`px-3 py-1 text-xs font-medium transition-colors ${
            mode === "edit"
              ? "bg-primary text-primary-foreground"
              : "bg-muted text-muted-foreground hover:bg-muted/80"
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
