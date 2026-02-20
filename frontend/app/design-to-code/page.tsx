"use client";

import { Suspense, useState, useCallback, useEffect, useMemo, useRef, useReducer } from "react";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Input } from "@/components/ui/input";
import { Card, CardContent } from "@/components/ui/card";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { FileEdit, Play, Palette, Link, Loader2 } from "lucide-react";

import { useDesignJob } from "./hooks/useDesignJob";
import { DesignEventFeed } from "./components/DesignEventFeed";
import { DesignOverview } from "./components/DesignOverview";
import { ScanResults } from "./components/ScanResults";
import { SpecBrowser } from "./spec-browser";
import { SpecTree } from "./spec-browser";
import { scanFigma, type FigmaScanResponse } from "@/lib/api";
import { useDesignJobHistory } from "./hooks/useDesignJobHistory";
import { DesignHistoryCard } from "./components/DesignHistoryCard";

// ---- Scan state machine (useReducer) ----
type ScanState = {
  step: "idle" | "scanning" | "selecting";
  result: FigmaScanResponse | null;
  error: string | null;
};

type ScanAction =
  | { type: "START_SCAN" }
  | { type: "SCAN_SUCCESS"; result: FigmaScanResponse }
  | { type: "SCAN_ERROR"; error: string }
  | { type: "RESET" };

const SCAN_INITIAL: ScanState = { step: "idle", result: null, error: null };

function scanReducer(_state: ScanState, action: ScanAction): ScanState {
  switch (action.type) {
    case "START_SCAN":
      return { step: "scanning", result: null, error: null };
    case "SCAN_SUCCESS":
      return { step: "selecting", result: action.result, error: null };
    case "SCAN_ERROR":
      return { step: "idle", result: null, error: action.error };
    case "RESET":
      return SCAN_INITIAL;
  }
}

/* ================================================================
   DesignToCodePage — Two-tab layout:
   Tab 1 (配置): Input form (design file path + output dir)
   Tab 2 (执行): Pipeline event feed + Overview panel
   Both tabs stay mounted (forceMount) to preserve SSE.
   ================================================================ */

const LS_KEY_OUTPUT_DIR = "design-to-code-output-dir";
const LS_KEY_FIGMA_URL = "design-to-code-figma-url";

export default function DesignToCodePage() {
  return (
    <Suspense
      fallback={
        <div className="flex h-full items-center justify-center text-muted-foreground">
          加载中...
        </div>
      }
    >
      <DesignToCodeContent />
    </Suspense>
  );
}

function DesignToCodeContent() {
  // Form inputs — initialize empty to avoid SSR hydration mismatch,
  // then load from localStorage after mount.
  const [figmaUrl, setFigmaUrl] = useState("");
  const [outputDir, setOutputDir] = useState("");

  const [activeTab, setActiveTab] = useState<string>("config");
  const [showCancelConfirm, setShowCancelConfirm] = useState(false);
  const [showLog, setShowLog] = useState(false);

  // Scan step state machine: idle → scanning → selecting
  const [scan, dispatchScan] = useReducer(scanReducer, SCAN_INITIAL);

  // Design job history
  const {
    historyJobs,
    loadingHistory,
    expandedJobId,
    expandedJobDetails,
    loadHistory,
    toggleJobDetails,
  } = useDesignJobHistory();

  // Hook
  const {
    currentJob,
    submitting,
    submitError,
    stats,
    events,
    sseConnected,
    currentNode,
    designSpec,
    specComplete,
    validation,
    tokenUsage,
    submit,
    cancel,
  } = useDesignJob();

  // Load persisted form values after mount (avoids SSR hydration mismatch)
  const didLoad = useRef(false);
  useEffect(() => {
    const f = localStorage.getItem(LS_KEY_FIGMA_URL);
    const o = localStorage.getItem(LS_KEY_OUTPUT_DIR);
    if (f) setFigmaUrl(f);
    if (o) setOutputDir(o);
    didLoad.current = true;
  }, []);

  // Persist form values (skip initial empty state before localStorage load)
  useEffect(() => {
    if (!didLoad.current) return;
    if (figmaUrl) localStorage.setItem(LS_KEY_FIGMA_URL, figmaUrl);
    else localStorage.removeItem(LS_KEY_FIGMA_URL);
  }, [figmaUrl]);

  useEffect(() => {
    if (!didLoad.current) return;
    if (outputDir) localStorage.setItem(LS_KEY_OUTPUT_DIR, outputDir);
    else localStorage.removeItem(LS_KEY_OUTPUT_DIR);
  }, [outputDir]);

  // Auto-switch to execution tab when job starts
  const jobActive =
    currentJob &&
    !["completed", "failed", "cancelled"].includes(currentJob.job_status);
  useEffect(() => {
    if (jobActive) setActiveTab("execution");
  }, [jobActive]);

  const hasJob = !!currentJob;

  // Dynamic execution tab label
  const executionTabSuffix = useMemo(() => {
    if (!currentJob) return "";
    switch (currentJob.job_status) {
      case "running":
      case "started":
        return ` (${stats.completed}/${stats.total} 生成中...)`;
      case "completed":
        return ` (${stats.completed}/${stats.total})`;
      case "failed":
        return ` (${stats.completed}/${stats.total})`;
      default:
        return "";
    }
  }, [currentJob?.job_status, stats.completed, stats.total]);

  const canSubmit =
    outputDir.trim().length > 0 && figmaUrl.trim().length > 0;

  // --- Scan Figma URL for frame classification ---
  const handleScan = useCallback(async () => {
    if (!figmaUrl.trim()) return;
    dispatchScan({ type: "START_SCAN" });
    try {
      const result = await scanFigma(figmaUrl.trim());
      dispatchScan({ type: "SCAN_SUCCESS", result });
    } catch (err) {
      const msg = err instanceof Error ? err.message : "扫描失败";
      dispatchScan({ type: "SCAN_ERROR", error: msg });
    }
  }, [figmaUrl]);

  // --- Submit spec pipeline ---
  const handleSubmit = useCallback(async () => {
    if (!canSubmit) return;
    const request = {
      figma_url: figmaUrl.trim(),
      output_dir: outputDir.trim(),
    };
    const result = await submit(request);
    if (result) {
      setActiveTab("execution");
    }
  }, [canSubmit, figmaUrl, outputDir, submit]);

  // --- Figma scan confirm → submit with selected_screens ---
  const handleScanConfirm = useCallback(
    async (selectedScreens: { node_id: string; interaction_note_ids: string[] }[]) => {
      const request = {
        figma_url: figmaUrl.trim(),
        output_dir: outputDir.trim(),
        selected_screens: selectedScreens,
      };
      const result = await submit(request);
      if (result) {
        dispatchScan({ type: "RESET" });
        setActiveTab("execution");
      }
    },
    [figmaUrl, outputDir, submit]
  );

  const handleScanBack = useCallback(() => {
    dispatchScan({ type: "RESET" });
  }, []);

  const handleNewJob = () => {
    setActiveTab("config");
    dispatchScan({ type: "RESET" });
  };

  const isFinished =
    currentJob &&
    ["completed", "failed", "cancelled"].includes(currentJob.job_status);

  return (
    <div className="flex h-full flex-col overflow-hidden">
      <div className="flex flex-1 flex-col overflow-hidden">
        {/* ---- Header ---- */}
        <div className="shrink-0 bg-card px-6 pt-5 pb-3">
          <div className="flex items-center gap-3 flex-wrap">
            <Palette className="h-5 w-5 text-violet-400" />
            <h1 className="text-lg font-semibold text-foreground">设计转规格</h1>
            {currentJob && (
              <div className="ml-auto flex items-center gap-2">
                <span className="rounded-full bg-violet-500/10 px-2.5 py-0.5 font-mono text-xs text-violet-400">
                  {currentJob.job_id}
                </span>
                <JobStatusBadge status={currentJob.job_status} />
              </div>
            )}
          </div>
        </div>
        {/* Gradient accent line */}
        <div className="h-[2px] bg-gradient-to-r from-violet-500 via-purple-400 to-pink-400 shrink-0" />

        {/* ---- Content ---- */}
        <div className="flex flex-1 flex-col overflow-hidden p-6 bg-background">
          <Tabs
            value={activeTab}
            onValueChange={setActiveTab}
            className="flex flex-1 flex-col overflow-hidden"
          >
            <TabsList className="mb-4 w-fit shrink-0 bg-card p-1 rounded-lg">
              <TabsTrigger
                value="config"
                className="rounded-md px-4 py-2 text-sm font-medium data-[state=active]:bg-violet-500 data-[state=active]:text-white data-[state=active]:shadow-sm text-muted-foreground"
              >
                <span className="inline-flex items-center gap-1.5">
                  <FileEdit className="h-3.5 w-3.5" /> 配置
                </span>
              </TabsTrigger>
              <TabsTrigger
                value="execution"
                disabled={!hasJob || undefined}
                className="rounded-md px-4 py-2 text-sm font-medium data-[state=active]:bg-violet-500 data-[state=active]:text-white data-[state=active]:shadow-sm text-muted-foreground disabled:opacity-40 disabled:cursor-not-allowed"
              >
                <span className="inline-flex items-center gap-1.5">
                  <Play className="h-3.5 w-3.5" /> 执行{executionTabSuffix}
                </span>
              </TabsTrigger>
            </TabsList>

            {/* ---- Config Tab ---- */}
            <TabsContent
              value="config"
              forceMount
              className="flex-1 overflow-hidden data-[state=inactive]:hidden"
            >
              {/* Scan selecting mode — full-width scan results */}
              {scan.step === "selecting" && scan.result ? (
                <div className="flex-1 h-full overflow-hidden">
                  <ScanResults
                    pageName={scan.result.page_name}
                    candidates={scan.result.candidates}
                    interactionSpecs={scan.result.interaction_specs}
                    designSystem={scan.result.design_system}
                    excluded={scan.result.excluded}
                    warnings={scan.result.warnings}
                    onConfirm={handleScanConfirm}
                    onBack={handleScanBack}
                  />
                </div>
              ) : (
                <div className="flex flex-1 h-full gap-6 overflow-hidden">
                  {/* Left: Input form */}
                  <div className="flex flex-1 flex-col gap-4 overflow-y-auto pr-2 max-w-2xl">
                    <Card>
                      <CardContent className="pt-4 pb-3 space-y-4">
                        <div className="space-y-2">
                          <Label className="text-xs">Figma 设计稿 URL</Label>
                          <Input
                            value={figmaUrl}
                            onChange={(e) => setFigmaUrl(e.target.value)}
                            placeholder="https://www.figma.com/design/6kGd851.../...?node-id=16650-538"
                            className="font-mono text-sm"
                          />
                          <p className="text-xs text-muted-foreground">
                            粘贴 Figma 设计稿链接，支持 /design/ 和 /file/
                            格式。可带 node-id 参数指定具体节点。
                          </p>
                        </div>

                        <div className="space-y-2">
                          <Label className="text-xs">输出目录</Label>
                          <Input
                            value={outputDir}
                            onChange={(e) => setOutputDir(e.target.value)}
                            placeholder="output/spec"
                            className="font-mono text-sm"
                          />
                          <p className="text-xs text-muted-foreground">
                            生成的 design_spec.json 将输出到此目录
                          </p>
                        </div>
                      </CardContent>
                    </Card>

                    {(submitError || scan.error) && (
                      <div className="rounded-md border border-red-500/30 bg-red-500/10 px-4 py-2.5">
                        <p className="text-sm text-red-400">{submitError || scan.error}</p>
                      </div>
                    )}

                    {/* Direct submit for both modes */}
                    <Button
                      className="w-fit bg-violet-500 hover:bg-violet-400 text-white"
                      onClick={handleSubmit}
                      disabled={submitting || !canSubmit}
                    >
                      <Play className="mr-1.5 h-3.5 w-3.5" />
                      {submitting ? "提交中..." : "生成设计规格"}
                    </Button>
                  </div>

                  {/* Right: Pipeline info card + History */}
                  <div className="w-[360px] shrink-0 overflow-y-auto space-y-4">
                    <Card>
                      <CardContent className="p-4 space-y-3">
                        <h3 className="text-sm font-semibold text-foreground">
                          Pipeline 流程
                        </h3>
                        <div className="space-y-2">
                          {PIPELINE_STAGES.map((stage, i) => (
                            <div
                              key={stage.icon}
                              className="flex items-start gap-2.5 text-xs"
                            >
                              <span className="shrink-0 mt-0.5 text-base">
                                {stage.icon}
                              </span>
                              <div>
                                <p className="font-medium text-foreground">
                                  {stage.label}
                                </p>
                                <p className="text-muted-foreground">{stage.desc}</p>
                              </div>
                            </div>
                          ))}
                        </div>
                      </CardContent>
                    </Card>

                    {/* History card */}
                    <Card>
                      <CardContent className="p-4">
                        <DesignHistoryCard
                          historyJobs={historyJobs}
                          loadingHistory={loadingHistory}
                          expandedJobId={expandedJobId}
                          expandedJobDetails={expandedJobDetails}
                          onRefresh={loadHistory}
                          onToggleDetails={toggleJobDetails}
                        />
                      </CardContent>
                    </Card>
                  </div>
                </div>
              )}
            </TabsContent>

            {/* ---- Execution Tab ---- */}
            <TabsContent
              value="execution"
              forceMount
              className="flex-1 overflow-hidden data-[state=inactive]:hidden"
            >
              {isFinished && currentJob ? (
                /* ---- Completed: Full-width code preview ---- */
                <div className="flex flex-1 h-full flex-col overflow-hidden">
                  {/* Compact status bar */}
                  <div className="flex items-center gap-3 rounded-lg bg-card px-4 py-2.5 mb-3 shrink-0">
                    <JobStatusBadge status={currentJob.job_status} />
                    <span className="text-xs text-foreground">
                      {stats.completed}/{stats.total} components
                    </span>
                    <span className="text-[11px] text-muted-foreground">
                      {currentJob.design_file ? currentJob.design_file.split("/").pop() : "Figma"}
                    </span>
                    <div className="flex-1" />
                    <Button
                      variant="outline"
                      size="sm"
                      className="h-7 text-xs"
                      onClick={handleNewJob}
                    >
                      New Job
                    </Button>
                    <Button
                      variant="ghost"
                      size="sm"
                      className="h-7 text-xs text-muted-foreground"
                      onClick={() => setShowLog((v) => !v)}
                    >
                      {showLog ? "Hide Log" : "Show Log"}
                    </Button>
                  </div>

                  {/* Token usage + validation banners */}
                  {tokenUsage && (tokenUsage.input_tokens > 0 || tokenUsage.output_tokens > 0) && (
                    <div className="rounded-lg border border-border bg-card/50 px-4 py-2 mb-3 shrink-0">
                      <div className="flex items-center gap-3 text-xs text-muted-foreground">
                        <span>Token 用量：</span>
                        <span>输入 <span className="text-foreground font-mono">{tokenUsage.input_tokens.toLocaleString()}</span></span>
                        <span>输出 <span className="text-foreground font-mono">{tokenUsage.output_tokens.toLocaleString()}</span></span>
                        <span className="text-muted-foreground">|</span>
                        <span>合计 <span className="text-foreground font-mono">{(tokenUsage.input_tokens + tokenUsage.output_tokens).toLocaleString()}</span></span>
                      </div>
                    </div>
                  )}
                  {validation && validation.auto_layout_compliant === false && (
                    <div className="rounded-lg border border-amber-500/30 bg-amber-500/10 px-4 py-2.5 mb-3 shrink-0">
                      <div className="flex items-center gap-2">
                        <span className="text-amber-400 text-sm">⚠</span>
                        <span className="text-xs text-amber-300">
                          {(validation.inferred_node_count as number) ?? 0} 个节点缺少 auto-layout — 请在 Figma 中补充后重跑
                        </span>
                      </div>
                    </div>
                  )}

                  {/* Main content: Log / SpecBrowser */}
                  {showLog ? (
                    <div className="flex-1 overflow-hidden">
                      <DesignEventFeed
                        events={events}
                        currentNode={currentNode}
                        sseConnected={sseConnected}
                        jobStatus={currentJob.job_status}
                      />
                    </div>
                  ) : designSpec ? (
                    <div className="flex-1 overflow-hidden">
                      <SpecBrowser
                        spec={designSpec}
                        jobId={currentJob.job_id}
                      />
                    </div>
                  ) : (
                    <div className="flex-1 flex items-center justify-center text-muted-foreground text-sm">
                      No design spec available.
                    </div>
                  )}
                </div>
              ) : (
                /* ---- Running: Log + Overview side-by-side ---- */
                <div className="flex flex-1 h-full gap-4 overflow-hidden">
                  {/* Left: Event Feed */}
                  <div className="flex-1 overflow-hidden">
                    <DesignEventFeed
                      events={events}
                      currentNode={currentNode}
                      sseConnected={sseConnected}
                      jobStatus={currentJob?.job_status}
                    />
                  </div>

                  {/* Right: Overview + live SpecTree */}
                  <div className="w-[360px] shrink-0 overflow-hidden flex flex-col gap-3">
                    <Card className="shrink-0">
                      <CardContent className="p-4">
                        <DesignOverview
                          currentJob={currentJob}
                          stats={stats}
                          components={designSpec?.components}
                          events={events}
                          tokenUsage={tokenUsage}
                        />
                        {/* Action buttons */}
                        <div className="mt-4 flex gap-2">
                          {currentJob && (
                            <Button
                              variant="outline"
                              size="sm"
                              className="flex-1 !text-red-400 !border-red-500/30 hover:!bg-red-500/10"
                              onClick={() => setShowCancelConfirm(true)}
                            >
                              Cancel
                            </Button>
                          )}
                          <Button
                            variant="outline"
                            size="sm"
                            className="flex-1"
                            onClick={handleNewJob}
                          >
                            New Job
                          </Button>
                        </div>
                      </CardContent>
                    </Card>

                    {/* Live SpecTree — progressive rendering as frames arrive */}
                    {designSpec && designSpec.components.length > 0 && (
                      <Card className="flex-1 min-h-0 overflow-hidden">
                        <CardContent className="p-0 h-full">
                          <SpecTree
                            components={designSpec.components}
                            selectedId={null}
                            onSelect={() => {}}
                          />
                        </CardContent>
                      </Card>
                    )}
                  </div>
                </div>
              )}
            </TabsContent>
          </Tabs>

          {/* Cancel confirmation dialog */}
          <AlertDialog
            open={showCancelConfirm}
            onOpenChange={setShowCancelConfirm}
          >
            <AlertDialogContent>
              <AlertDialogHeader>
                <AlertDialogTitle>确认取消？</AlertDialogTitle>
                <AlertDialogDescription>
                  当前任务进度 {stats.completed}/{stats.total}{" "}
                  完成。取消后正在执行的组件生成将被中断。
                </AlertDialogDescription>
              </AlertDialogHeader>
              <AlertDialogFooter>
                <AlertDialogCancel>继续执行</AlertDialogCancel>
                <AlertDialogAction
                  className="bg-red-600 hover:bg-red-700 text-white"
                  onClick={() => {
                    cancel();
                    setShowCancelConfirm(false);
                  }}
                >
                  确认取消
                </AlertDialogAction>
              </AlertDialogFooter>
            </AlertDialogContent>
          </AlertDialog>
        </div>
      </div>
    </div>
  );
}

/* ================================================================
   Pipeline Stages Info
   ================================================================ */

const PIPELINE_STAGES = [
  {
    icon: "1\uFE0F\u20E3",
    label: "Figma 数据获取",
    desc: "获取 Figma 节点树、截图和 Design Tokens（颜色/字体/间距）",
  },
  {
    icon: "2\uFE0F\u20E3",
    label: "结构分解",
    desc: "解析节点树，提取组件层级、布局、样式和尺寸信息（70% 数据）",
  },
  {
    icon: "3\uFE0F\u20E3",
    label: "语义分析",
    desc: "AI 分析每个组件的语义角色、描述和交互行为（30% 数据）",
  },
  {
    icon: "4\uFE0F\u20E3",
    label: "规格组装",
    desc: "合并结构和语义数据，输出完整 design_spec.json",
  },
];

/* ================================================================
   Job Status Badge
   ================================================================ */

function JobStatusBadge({ status }: { status: string }) {
  const config: Record<
    string,
    { bg: string; dotColor: string; text: string; label: string }
  > = {
    started: {
      bg: "#dbeafe",
      dotColor: "#3b82f6",
      text: "#2563eb",
      label: "启动中",
    },
    running: {
      bg: "#dcfce7",
      dotColor: "#22c55e",
      text: "#16a34a",
      label: "生成中",
    },
    completed: {
      bg: "#dcfce7",
      dotColor: "#22c55e",
      text: "#16a34a",
      label: "已完成",
    },
    failed: {
      bg: "#fef2f2",
      dotColor: "#ef4444",
      text: "#dc2626",
      label: "失败",
    },
    cancelled: {
      bg: "#fef3c7",
      dotColor: "#f59e0b",
      text: "#d97706",
      label: "已取消",
    },
  };
  const c = config[status] ?? config.running;

  return (
    <span
      className="inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5"
      style={{ backgroundColor: c.bg }}
    >
      <span
        className={`h-2 w-2 rounded-full ${
          status === "running" || status === "started" ? "animate-pulse" : ""
        }`}
        style={{ backgroundColor: c.dotColor }}
      />
      <span className="text-xs font-medium" style={{ color: c.text }}>
        {c.label}
      </span>
    </span>
  );
}
