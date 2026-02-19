"use client";

import { useState, useCallback, useEffect } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
  DialogDescription,
} from "@/components/ui/dialog";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

interface DirectoryEntry {
  name: string;
  path: string;
  is_dir: boolean;
}

interface BrowseResponse {
  current_path: string;
  parent_path: string | null;
  entries: DirectoryEntry[];
}

interface DirectoryPickerProps {
  value: string;
  onChange: (path: string) => void;
}

export function DirectoryPicker({ value, onChange }: DirectoryPickerProps) {
  const [open, setOpen] = useState(false);
  const [currentPath, setCurrentPath] = useState("/");
  const [parentPath, setParentPath] = useState<string | null>(null);
  const [entries, setEntries] = useState<DirectoryEntry[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [manualInput, setManualInput] = useState("");

  const browse = useCallback(async (path: string) => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(
        `${API_BASE}/api/v2/filesystem/browse?path=${encodeURIComponent(path)}`
      );
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }));
        throw new Error(err.detail || "Failed to browse directory");
      }
      const data: BrowseResponse = await res.json();
      setCurrentPath(data.current_path);
      setParentPath(data.parent_path);
      setEntries(data.entries);
      setManualInput(data.current_path);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Unknown error");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (open) {
      browse(value || "/");
    }
  }, [open, value, browse]);

  const handleSelect = () => {
    onChange(currentPath);
    setOpen(false);
  };

  const handleManualGo = () => {
    if (manualInput.trim()) {
      browse(manualInput.trim());
    }
  };

  return (
    <>
      <div className="flex gap-2">
        <Input
          readOnly
          value={value || ""}
          placeholder="点击右侧按钮选择目录..."
          className="text-sm font-mono flex-1 bg-input-bg cursor-pointer"
          onClick={() => setOpen(true)}
        />
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={() => setOpen(true)}
          className="shrink-0"
        >
          浏览...
        </Button>
      </div>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="sm:max-w-[560px]">
          <DialogHeader>
            <DialogTitle>选择目标代码库目录</DialogTitle>
            <DialogDescription>
              选择 Claude CLI 的工作目录，即需要修复的项目代码库所在路径
            </DialogDescription>
          </DialogHeader>

          {/* Manual path input */}
          <div className="flex gap-2">
            <Input
              value={manualInput}
              onChange={(e) => setManualInput(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && handleManualGo()}
              placeholder="输入路径..."
              className="text-sm font-mono flex-1"
            />
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={handleManualGo}
              disabled={loading}
            >
              前往
            </Button>
          </div>

          {/* Breadcrumb */}
          <div className="flex items-center gap-1 text-xs text-muted-foreground overflow-x-auto">
            {currentPath.split("/").filter(Boolean).map((segment, i, arr) => {
              const segPath = "/" + arr.slice(0, i + 1).join("/");
              return (
                <span key={segPath} className="flex items-center gap-1">
                  {i > 0 && <span className="text-muted-foreground">/</span>}
                  <button
                    className="hover:text-primary hover:underline"
                    onClick={() => browse(segPath)}
                  >
                    {segment}
                  </button>
                </span>
              );
            })}
          </div>

          {/* Directory listing */}
          <div className="border rounded-md max-h-[300px] overflow-y-auto">
            {error && (
              <div className="p-3 text-sm text-red-400 bg-red-500/10">{error}</div>
            )}

            {loading && (
              <div className="p-3 text-sm text-muted-foreground">加载中...</div>
            )}

            {!loading && !error && (
              <>
                {/* Parent directory */}
                {parentPath && (
                  <button
                    className="w-full text-left px-3 py-2 text-sm hover:bg-muted border-b border-border flex items-center gap-2"
                    onClick={() => browse(parentPath)}
                  >
                    <span className="text-muted-foreground">↑</span>
                    <span className="text-muted-foreground">..</span>
                  </button>
                )}

                {/* Directories */}
                {entries.length === 0 && (
                  <div className="p-3 text-sm text-muted-foreground">
                    此目录下没有子目录
                  </div>
                )}
                {entries.map((entry) => (
                  <button
                    key={entry.path}
                    className="w-full text-left px-3 py-2 text-sm hover:bg-primary/10 border-b border-border last:border-b-0 flex items-center gap-2"
                    onClick={() => browse(entry.path)}
                  >
                    <span className="text-primary">📁</span>
                    <span>{entry.name}</span>
                  </button>
                ))}
              </>
            )}
          </div>

          <DialogFooter>
            <div className="flex items-center justify-between w-full">
              <span className="text-xs text-muted-foreground font-mono truncate max-w-[300px]">
                {currentPath}
              </span>
              <Button onClick={handleSelect} size="sm">
                选择此目录
              </Button>
            </div>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
