"use client";

import { useState, useCallback } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Textarea } from "@/components/ui/textarea";
import { Input } from "@/components/ui/input";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Checkbox } from "@/components/ui/checkbox";
import { Badge } from "@/components/ui/badge";
import { useToast } from "@/components/hooks/use-toast";
import { queryJiraBugs } from "@/lib/api";
import type { JiraBug } from "../types";

interface BugInputProps {
  jiraUrls: string;
  onJiraUrlsChange: (urls: string) => void;
  parseJiraUrls: () => string[];
}

export function BugInput({
  jiraUrls,
  onJiraUrlsChange,
  parseJiraUrls,
}: BugInputProps) {
  const { toast } = useToast();
  const [inputMode, setInputMode] = useState<"url" | "jql">("url");
  const [jqlQuery, setJqlQuery] = useState("");
  const [jqlResults, setJqlResults] = useState<JiraBug[]>([]);
  const [selectedBugKeys, setSelectedBugKeys] = useState<Set<string>>(
    new Set()
  );
  const [loadingJql, setLoadingJql] = useState(false);

  const handleJqlQuery = useCallback(async () => {
    if (!jqlQuery.trim()) {
      toast({
        title: "请输入 JQL 查询语句",
        variant: "destructive",
      });
      return;
    }

    setLoadingJql(true);
    try {
      const data = await queryJiraBugs({
        jql: jqlQuery.trim(),
        max_results: 50,
      });
      setJqlResults(data.bugs);
      setSelectedBugKeys(new Set(data.bugs.map((b) => b.key)));
      toast({
        title: "查询成功",
        description: `找到 ${data.total} 个 Bug`,
      });
    } catch (err) {
      toast({
        title: "查询失败",
        description: err instanceof Error ? err.message : "未知错误",
        variant: "destructive",
      });
      setJqlResults([]);
      setSelectedBugKeys(new Set());
    } finally {
      setLoadingJql(false);
    }
  }, [jqlQuery, toast]);

  const toggleBugSelection = useCallback((key: string) => {
    setSelectedBugKeys((prev) => {
      const next = new Set(prev);
      if (next.has(key)) {
        next.delete(key);
      } else {
        next.add(key);
      }
      return next;
    });
  }, []);

  const toggleSelectAll = useCallback(() => {
    if (selectedBugKeys.size === jqlResults.length) {
      setSelectedBugKeys(new Set());
    } else {
      setSelectedBugKeys(new Set(jqlResults.map((b) => b.key)));
    }
  }, [jqlResults, selectedBugKeys.size]);

  const importSelectedBugs = useCallback(() => {
    const selectedBugs = jqlResults.filter((b) => selectedBugKeys.has(b.key));
    if (selectedBugs.length === 0) {
      toast({
        title: "请选择要导入的 Bug",
        variant: "destructive",
      });
      return;
    }
    const urls = selectedBugs.map((b) => b.url).join("\n");
    onJiraUrlsChange(urls);
    setInputMode("url");
    toast({
      title: "导入成功",
      description: `已导入 ${selectedBugs.length} 个 Bug 链接`,
    });
  }, [jqlResults, selectedBugKeys, toast, onJiraUrlsChange]);

  return (
    <Card>
      <CardHeader className="py-3">
        <CardTitle className="text-sm">Jira Bug 链接</CardTitle>
      </CardHeader>
      <CardContent>
        <Tabs
          value={inputMode}
          onValueChange={(v) => setInputMode(v as "url" | "jql")}
        >
          <TabsList>
            <TabsTrigger value="url">URL 模式</TabsTrigger>
            <TabsTrigger value="jql">JQL 查询</TabsTrigger>
          </TabsList>

          <TabsContent value="url">
            <Textarea
              placeholder={`每行一个 Jira Bug 链接，例如：
https://jira.example.com/browse/BUG-1234
https://jira.example.com/browse/BUG-1235
https://jira.example.com/browse/BUG-1236`}
              value={jiraUrls}
              onChange={(e) => onJiraUrlsChange(e.target.value)}
              className="min-h-[160px] font-mono text-sm"
            />
            <p className="mt-2 text-xs text-muted-foreground">
              已输入 {parseJiraUrls().length} 个链接
            </p>
          </TabsContent>

          <TabsContent value="jql">
            <div className="space-y-3">
              <div className="flex gap-2">
                <Input
                  placeholder="输入 JQL 查询语句，如：project = BUG AND type = Bug"
                  value={jqlQuery}
                  onChange={(e) => setJqlQuery(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && handleJqlQuery()}
                  className="flex-1 font-mono text-sm"
                />
                <Button
                  onClick={handleJqlQuery}
                  disabled={loadingJql || !jqlQuery.trim()}
                  variant="outline"
                >
                  {loadingJql ? "查询中..." : "查询"}
                </Button>
              </div>

              {jqlResults.length > 0 && (
                <div className="space-y-2">
                  <div className="flex items-center justify-between">
                    <p className="text-xs text-muted-foreground">
                      找到 {jqlResults.length} 个 Bug，已选择{" "}
                      {selectedBugKeys.size} 个
                    </p>
                    <div className="flex gap-2">
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={toggleSelectAll}
                        className="h-6 px-2 text-xs"
                      >
                        {selectedBugKeys.size === jqlResults.length
                          ? "取消全选"
                          : "全选"}
                      </Button>
                      <Button
                        size="sm"
                        onClick={importSelectedBugs}
                        disabled={selectedBugKeys.size === 0}
                        className="h-6 px-2 text-xs"
                      >
                        导入选中 ({selectedBugKeys.size})
                      </Button>
                    </div>
                  </div>

                  <div className="max-h-[200px] overflow-y-auto rounded-md border border-border">
                    {jqlResults.map((bug) => (
                      <div
                        key={bug.key}
                        className="flex items-center gap-3 border-b border-border px-3 py-2 last:border-b-0 hover:bg-muted"
                      >
                        <Checkbox
                          checked={selectedBugKeys.has(bug.key)}
                          onCheckedChange={() => toggleBugSelection(bug.key)}
                        />
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-2">
                            <span className="font-mono text-sm font-medium text-primary">
                              {bug.key}
                            </span>
                            <Badge className="border-border bg-muted/50 text-card-foreground text-xs">
                              {bug.status}
                            </Badge>
                            {bug.priority && (
                              <span className="text-xs text-muted-foreground">
                                {bug.priority}
                              </span>
                            )}
                          </div>
                          <p className="truncate text-xs text-muted-foreground">
                            {bug.summary}
                          </p>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {jqlResults.length === 0 && jqlQuery && !loadingJql && (
                <p className="text-center text-xs text-muted-foreground py-4">
                  输入 JQL 查询语句并点击查询
                </p>
              )}
            </div>
          </TabsContent>
        </Tabs>
      </CardContent>
    </Card>
  );
}
