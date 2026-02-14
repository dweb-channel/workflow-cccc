import { useState, useEffect, useCallback } from "react";
import {
  listWorkspaces,
  createWorkspace,
  updateWorkspace,
  deleteWorkspace,
  type Workspace,
  type CreateWorkspaceRequest,
  type UpdateWorkspaceRequest,
} from "@/lib/api";
import { useToast } from "@/components/hooks/use-toast";

export function useWorkspaces() {
  const { toast } = useToast();
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      const resp = await listWorkspaces();
      setWorkspaces(resp.workspaces);
    } catch (err) {
      const msg = err instanceof Error ? err.message : "加载项目组失败";
      setError(msg);
      console.warn("Failed to load workspaces:", msg);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const create = useCallback(
    async (req: CreateWorkspaceRequest) => {
      try {
        const ws = await createWorkspace(req);
        setWorkspaces((prev) => [ws, ...prev]);
        toast({ title: "项目组已创建", description: ws.name });
        return ws;
      } catch (err) {
        toast({
          title: "创建失败",
          description: err instanceof Error ? err.message : "未知错误",
          variant: "destructive",
        });
        return null;
      }
    },
    [toast]
  );

  const update = useCallback(
    async (id: string, req: UpdateWorkspaceRequest) => {
      try {
        const ws = await updateWorkspace(id, req);
        setWorkspaces((prev) => prev.map((w) => (w.id === id ? ws : w)));
        toast({ title: "项目组已更新", description: ws.name });
        return ws;
      } catch (err) {
        toast({
          title: "更新失败",
          description: err instanceof Error ? err.message : "未知错误",
          variant: "destructive",
        });
        return null;
      }
    },
    [toast]
  );

  const remove = useCallback(
    async (id: string) => {
      try {
        await deleteWorkspace(id);
        setWorkspaces((prev) => prev.filter((w) => w.id !== id));
        toast({ title: "项目组已删除" });
        return true;
      } catch (err) {
        toast({
          title: "删除失败",
          description: err instanceof Error ? err.message : "未知错误",
          variant: "destructive",
        });
        return false;
      }
    },
    [toast]
  );

  return { workspaces, loading, error, reload: load, create, update, remove };
}
