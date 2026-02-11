"use client";

import type { BugStep, StepStatus } from "../types";

/** The 3 user-visible steps. Backend maps 10+ nodes to these. */
const VISIBLE_STEPS = ["fix_bug_peer", "verify_fix", "update_success"] as const;

const STEP_LABELS: Record<string, string> = {
  fix_bug_peer: "修复",
  verify_fix: "验证",
  update_success: "完成",
};

interface BugStepperProps {
  steps?: BugStep[];
  bugStatus: string;
  retryCount?: number;
}

function getStepState(
  stepKey: string,
  steps: BugStep[] | undefined,
  bugStatus: string
): { status: StepStatus; duration_ms?: number; output_preview?: string; attempt?: number } {
  if (!steps || steps.length === 0) {
    // Degraded mode: derive from bug-level status
    if (bugStatus === "pending") return { status: "pending" };
    if (bugStatus === "in_progress") {
      return stepKey === "fix_bug_peer"
        ? { status: "in_progress" }
        : { status: "pending" };
    }
    if (bugStatus === "completed") return { status: "completed" };
    if (bugStatus === "failed") {
      // Show last step as failed
      return stepKey === "update_success"
        ? { status: "failed" }
        : { status: "completed" };
    }
    return { status: "pending" };
  }

  // Find matching step(s) — use last occurrence for retries
  const matching = steps.filter((s) => s.step === stepKey);
  if (matching.length === 0) {
    // For update_success, also check update_failure
    if (stepKey === "update_success") {
      const failMatch = steps.filter((s) => s.step === "update_failure");
      if (failMatch.length > 0) {
        const last = failMatch[failMatch.length - 1];
        return {
          status: "failed",
          duration_ms: last.duration_ms,
          output_preview: last.output_preview,
          attempt: last.attempt,
        };
      }
    }
    // No step data found — infer from bug-level status
    if (bugStatus === "completed") return { status: "completed" };
    if (bugStatus === "failed") {
      return stepKey === "update_success"
        ? { status: "failed" }
        : { status: "completed" };
    }
    return { status: "pending" };
  }

  const last = matching[matching.length - 1];
  return {
    status: last.status,
    duration_ms: last.duration_ms,
    output_preview: last.output_preview,
    attempt: last.attempt,
  };
}

function StepIcon({ status }: { status: StepStatus }) {
  if (status === "completed") {
    return (
      <div
        className="flex h-7 w-7 items-center justify-center rounded-full bg-green-500 text-white text-xs font-bold"
        data-status="completed"
      >
        ✓
      </div>
    );
  }
  if (status === "in_progress") {
    return (
      <div
        className="flex h-7 w-7 items-center justify-center rounded-full border-2 border-blue-500 bg-blue-50 animate-pulse"
        data-status="in_progress"
      >
        <div className="h-2.5 w-2.5 rounded-full bg-blue-500" />
      </div>
    );
  }
  if (status === "failed") {
    return (
      <div
        className="flex h-7 w-7 items-center justify-center rounded-full bg-red-500 text-white text-xs font-bold"
        data-status="failed"
      >
        ✗
      </div>
    );
  }
  // pending
  return (
    <div
      className="flex h-7 w-7 items-center justify-center rounded-full border-2 border-slate-300 bg-white"
      data-status="pending"
    >
      <div className="h-2 w-2 rounded-full bg-slate-300" />
    </div>
  );
}

function ConnectorLine({ status }: { status: StepStatus }) {
  const color =
    status === "completed"
      ? "bg-green-500"
      : status === "in_progress"
        ? "bg-blue-300"
        : status === "failed"
          ? "bg-red-300"
          : "bg-slate-200";
  return <div className={`h-0.5 w-full ${color}`} />;
}

export function BugStepper({ steps, bugStatus, retryCount }: BugStepperProps) {
  return (
    <div className="space-y-3">
      {/* Stepper row */}
      <div className="flex items-center gap-1">
        {VISIBLE_STEPS.map((stepKey, idx) => {
          const state = getStepState(stepKey, steps, bugStatus);
          const label = STEP_LABELS[stepKey];

          return (
            <div key={stepKey} className="flex flex-1 items-center">
              <div
                className="flex flex-col items-center gap-1"
                data-testid={`step-${stepKey}`}
              >
                <StepIcon status={state.status} />
                <span className="text-[10px] text-slate-600 whitespace-nowrap">
                  {label}
                  {stepKey === "verify_fix" &&
                    retryCount !== undefined &&
                    retryCount > 0 && (
                      <span className="ml-0.5 rounded bg-orange-100 px-1 text-orange-600 font-medium">
                        ×{retryCount + 1}
                      </span>
                    )}
                </span>
                {state.duration_ms !== undefined && (
                  <span className="text-[9px] text-slate-400">
                    {(state.duration_ms / 1000).toFixed(1)}s
                  </span>
                )}
              </div>
              {idx < VISIBLE_STEPS.length - 1 && (
                <div className="mx-1 flex-1">
                  <ConnectorLine status={state.status} />
                </div>
              )}
            </div>
          );
        })}
      </div>

      {/* Output previews */}
      {steps && steps.length > 0 && (
        <div className="space-y-1.5">
          {VISIBLE_STEPS.map((stepKey) => {
            const state = getStepState(stepKey, steps, bugStatus);
            if (!state.output_preview) return null;
            const preview = state.output_preview;
            return (
              <div
                key={stepKey}
                className="rounded bg-slate-50 px-2.5 py-1.5 text-xs text-slate-600"
              >
                <span className="font-medium text-slate-500">
                  {STEP_LABELS[stepKey]}:{" "}
                </span>
                <span className="break-words">
                  {preview.length > 200
                    ? preview.slice(0, 200) + "..."
                    : preview}
                </span>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
