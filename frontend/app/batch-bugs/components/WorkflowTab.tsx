"use client";

/**
 * Static workflow diagram showing the batch bug fix process.
 * Helps new users understand what happens after they submit a job.
 */
export function WorkflowTab() {
  return (
    <div className="space-y-6">
      {/* Title */}
      <div>
        <h3 className="text-base font-semibold text-slate-800">
          批量修复流程
        </h3>
        <p className="mt-1 text-xs text-slate-500">
          提交后，系统按以下流程依次处理每个 Bug
        </p>
      </div>

      {/* Flowchart */}
      <div className="flex flex-col items-center gap-0">
        {/* Step 1: Input */}
        <StepNode
          number={1}
          label="输入 Bug"
          description="解析 Jira URL，提取 Bug 详情"
          color="blue"
        />
        <Arrow />

        {/* Step 2: Fix */}
        <StepNode
          number={2}
          label="AI 修复"
          description="CCCC Peer 分析代码并实施修复"
          color="indigo"
        />
        <Arrow />

        {/* Step 3: Verify */}
        <StepNode
          number={3}
          label="验证修复"
          description="Peer 运行测试，确认修复有效"
          color="violet"
        />
        <Arrow />

        {/* Step 4: Decision */}
        <div className="flex items-center gap-4">
          {/* Left: retry loop */}
          <div className="flex flex-col items-center">
            <div className="rounded border border-dashed border-orange-300 bg-orange-50 px-3 py-1 text-xs text-orange-600">
              验证失败 → 重试
            </div>
            <svg width="24" height="48" className="text-orange-400">
              <path
                d="M12 0 L12 16 Q12 24 4 24 L4 24 Q-4 24 -4 32"
                fill="none"
                stroke="currentColor"
                strokeWidth="1.5"
                strokeDasharray="4 3"
              />
            </svg>
            <div className="text-[10px] text-orange-400">↑ 回到步骤 2</div>
          </div>

          {/* Decision diamond */}
          <div className="relative flex h-20 w-40 items-center justify-center">
            <div className="absolute inset-0 rotate-0">
              <div className="flex h-full w-full items-center justify-center rounded-lg border-2 border-amber-400 bg-amber-50">
                <div className="text-center">
                  <div className="text-sm font-medium text-amber-700">
                    结果判断
                  </div>
                  <div className="text-[10px] text-amber-500">
                    通过 / 失败 / 重试
                  </div>
                </div>
              </div>
            </div>
          </div>

          {/* Right: skip */}
          <div className="flex flex-col items-center">
            <div className="rounded border border-dashed border-slate-300 bg-slate-50 px-3 py-1 text-xs text-slate-500">
              跳过 / 停止
            </div>
            <div className="text-[10px] text-slate-400 mt-1">
              按失败策略处理
            </div>
          </div>
        </div>

        <Arrow />

        {/* Step 5: Complete */}
        <StepNode
          number={5}
          label="完成"
          description="更新状态，处理下一个 Bug"
          color="green"
        />
      </div>

      {/* Config reference */}
      <div className="rounded-lg border border-slate-200 bg-slate-50 p-4 space-y-3">
        <h4 className="text-sm font-medium text-slate-700">配置说明</h4>
        <div className="grid grid-cols-3 gap-3 text-xs">
          <ConfigItem
            title="验证级别"
            items={["快速 — 基础检查", "标准 — 运行测试", "全面 — 完整回归"]}
          />
          <ConfigItem
            title="失败策略"
            items={["继续 — 跳过失败，继续下一个", "停止 — 遇到失败立即停止"]}
          />
          <ConfigItem
            title="重试机制"
            items={["验证失败自动重试", "最多重试 3 次", "超过后按失败策略处理"]}
          />
        </div>
      </div>
    </div>
  );
}

/* ---- Sub-components ---- */

const COLORS = {
  blue: {
    border: "border-blue-200",
    bg: "bg-blue-50",
    number: "bg-blue-500",
    text: "text-blue-800",
    desc: "text-blue-500",
  },
  indigo: {
    border: "border-indigo-200",
    bg: "bg-indigo-50",
    number: "bg-indigo-500",
    text: "text-indigo-800",
    desc: "text-indigo-500",
  },
  violet: {
    border: "border-violet-200",
    bg: "bg-violet-50",
    number: "bg-violet-500",
    text: "text-violet-800",
    desc: "text-violet-500",
  },
  green: {
    border: "border-green-200",
    bg: "bg-green-50",
    number: "bg-green-500",
    text: "text-green-800",
    desc: "text-green-500",
  },
} as const;

function StepNode({
  number,
  label,
  description,
  color,
}: {
  number: number;
  label: string;
  description: string;
  color: keyof typeof COLORS;
}) {
  const c = COLORS[color];
  return (
    <div
      className={`flex w-64 items-center gap-3 rounded-lg border ${c.border} ${c.bg} px-4 py-3`}
    >
      <div
        className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-full ${c.number} text-xs font-bold text-white`}
      >
        {number}
      </div>
      <div>
        <div className={`text-sm font-medium ${c.text}`}>{label}</div>
        <div className={`text-[11px] ${c.desc}`}>{description}</div>
      </div>
    </div>
  );
}

function Arrow() {
  return (
    <div className="flex h-6 items-center justify-center">
      <svg width="12" height="24" className="text-slate-300">
        <line
          x1="6"
          y1="0"
          x2="6"
          y2="18"
          stroke="currentColor"
          strokeWidth="2"
        />
        <polygon points="2,16 6,22 10,16" fill="currentColor" />
      </svg>
    </div>
  );
}

function ConfigItem({ title, items }: { title: string; items: string[] }) {
  return (
    <div className="space-y-1">
      <div className="font-medium text-slate-600">{title}</div>
      <ul className="space-y-0.5 text-slate-500">
        {items.map((item) => (
          <li key={item}>· {item}</li>
        ))}
      </ul>
    </div>
  );
}
