"use client";

import { useState, useCallback, useEffect } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useToast } from "@/components/hooks/use-toast";
import { getCCCCGroups } from "@/lib/api";
import type { CCCCGroup, CCCCPeer } from "../types";

interface GroupSelectorProps {
  selectedGroupId: string | null;
  fixerPeerId: string | null;
  verifierPeerId: string | null;
  onGroupChange: (groupId: string, group: CCCCGroup | undefined) => void;
  onFixerChange: (peerId: string) => void;
  onVerifierChange: (peerId: string) => void;
}

export function GroupSelector({
  selectedGroupId,
  fixerPeerId,
  verifierPeerId,
  onGroupChange,
  onFixerChange,
  onVerifierChange,
}: GroupSelectorProps) {
  const { toast } = useToast();
  const [groups, setGroups] = useState<CCCCGroup[]>([]);
  const [loadingGroups, setLoadingGroups] = useState(false);

  const loadGroups = useCallback(async () => {
    setLoadingGroups(true);
    try {
      const data = await getCCCCGroups("running");
      setGroups(data.groups);
      if (data.groups.length === 0) {
        toast({
          title: "没有可用的 Group",
          description: "请先启动一个 CCCC Group",
          variant: "default",
        });
      }
    } catch (err) {
      toast({
        title: "加载 Groups 失败",
        description: err instanceof Error ? err.message : "未知错误",
        variant: "destructive",
      });
    } finally {
      setLoadingGroups(false);
    }
  }, [toast]);

  useEffect(() => {
    loadGroups();
  }, [loadGroups]);

  const selectedGroup = groups.find((g) => g.group_id === selectedGroupId);
  const availablePeers: CCCCPeer[] = selectedGroup?.peers ?? [];

  const handleGroupSelect = useCallback(
    (groupId: string) => {
      const group = groups.find((g) => g.group_id === groupId);
      onGroupChange(groupId, group);
    },
    [groups, onGroupChange]
  );

  return (
    <Card>
      <CardHeader className="py-3">
        <CardTitle className="text-sm">目标 Group</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <Select
          value={selectedGroupId || ""}
          onValueChange={handleGroupSelect}
          disabled={loadingGroups}
        >
          <SelectTrigger>
            <SelectValue placeholder="选择目标 Group" />
          </SelectTrigger>
          <SelectContent>
            {groups.length === 0 ? (
              <SelectItem value="__empty" disabled>
                暂无可用 Group
              </SelectItem>
            ) : (
              groups
                .filter((g) => g.running && g.state === "active")
                .map((g) => (
                  <SelectItem
                    key={g.group_id}
                    value={g.group_id}
                    disabled={!g.ready}
                  >
                    {g.title} · {g.enabled_peers} peers
                    {!g.ready && " (不可用)"}
                  </SelectItem>
                ))
            )}
          </SelectContent>
        </Select>

        {selectedGroup && (
          <div className="flex items-center gap-2 text-xs">
            <span
              className={`h-2 w-2 rounded-full ${
                selectedGroup.ready ? "bg-green-500" : "bg-slate-400"
              }`}
            />
            <span className="text-slate-600">
              {selectedGroup.ready ? "运行中" : "不可用"} ·{" "}
              {selectedGroup.enabled_peers} 个 peer 可用
            </span>
          </div>
        )}

        {selectedGroup && availablePeers.length > 0 && (
          <div className="grid grid-cols-2 gap-3 pt-2 border-t">
            <div className="space-y-1">
              <Label className="text-xs">修复执行者</Label>
              <Select
                value={fixerPeerId || ""}
                onValueChange={onFixerChange}
              >
                <SelectTrigger>
                  <SelectValue placeholder="选择 Peer (可选)" />
                </SelectTrigger>
                <SelectContent>
                  {availablePeers.map((peer) => (
                    <SelectItem key={peer.id} value={peer.id}>
                      <span className="flex items-center gap-2">
                        <span>{peer.running ? "🟢" : "🔴"}</span>
                        <span>
                          {peer.title} ({peer.id})
                        </span>
                      </span>
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1">
              <Label className="text-xs">验证执行者</Label>
              <Select
                value={verifierPeerId || ""}
                onValueChange={onVerifierChange}
              >
                <SelectTrigger>
                  <SelectValue placeholder="选择 Peer (可选)" />
                </SelectTrigger>
                <SelectContent>
                  {availablePeers.map((peer) => (
                    <SelectItem key={peer.id} value={peer.id}>
                      <span className="flex items-center gap-2">
                        <span>{peer.running ? "🟢" : "🔴"}</span>
                        <span>
                          {peer.title} ({peer.id})
                        </span>
                      </span>
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>
        )}

        <Button
          variant="outline"
          size="sm"
          onClick={loadGroups}
          disabled={loadingGroups}
        >
          {loadingGroups ? "加载中..." : "刷新 Groups"}
        </Button>
      </CardContent>
    </Card>
  );
}
