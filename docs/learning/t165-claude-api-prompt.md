# Claude API + Prompt Engineering 教学材料

> 基于 work-flow 项目真实代码，讲解 Claude CLI 调用、Tool Use、stream-json 模式、Prompt 模板设计，以及项目中踩过的坑。
>
> **前置阅读**：如果你已经读完 [T164 项目架构全景](./t164-architecture-overview.md) 的"管线 2: Design-to-Spec"数据流图，本文将深入讲解其中 Claude CLI 的调用细节、Tool Use 策略和 Prompt 设计。

---

## 目录

- [S1: Claude API 基础教程](#s1-claude-api-基础教程)
  - [1.1 Claude CLI vs HTTP API](#11-claude-cli-vs-http-api)
  - [1.2 输出格式：json vs stream-json](#12-输出格式json-vs-stream-json)
  - [1.3 项目中的统一封装：claude_cli_wrapper.py](#13-项目中的统一封装claude_cli_wrapperpy)
  - [1.4 Oneshot 模式详解](#14-oneshot-模式详解)
  - [1.5 Stream 模式详解](#15-stream-模式详解)
  - [1.6 System Prompt 的拼接方式](#16-system-prompt-的拼接方式)
- [S2: Tool Use 实战指南](#s2-tool-use-实战指南)
  - [2.1 什么是 Tool Use](#21-什么是-tool-use)
  - [2.2 --allowedTools 精确控制](#22---allowedtools-精确控制)
  - [2.3 --tools "" 完全禁用工具](#23---tools--完全禁用工具)
  - [2.4 项目中的三种 Tool 策略](#24-项目中的三种-tool-策略)
  - [2.5 Tool Use 事件解析](#25-tool-use-事件解析)
- [S3: Prompt 踩坑集锦](#s3-prompt-踩坑集锦)
  - [3.1 Write 工具 vs 文本输出：result 只含最后一条 assistant text](#31-write-工具-vs-文本输出result-只含最后一条-assistant-text)
  - [3.2 中文引号 vs JSON 引号冲突](#32-中文引号-vs-json-引号冲突)
  - [3.3 JSON 输出的 5 级恢复链](#33-json-输出的-5-级恢复链)
  - [3.4 Two-Pass 架构：为什么要分两步](#34-two-pass-架构为什么要分两步)
  - [3.5 Prompt 中的输出约束心法](#35-prompt-中的输出约束心法)
  - [3.6 截图传递：多模态分析](#36-截图传递多模态分析)
  - [3.7 重试与错误反馈](#37-重试与错误反馈)
- [关键文件索引](#关键文件索引)
- [练习建议](#练习建议)

---

## S1: Claude API 基础教程

### 1.1 Claude CLI vs HTTP API

Claude 提供两种调用方式：

| 对比项 | HTTP API (Anthropic SDK) | Claude CLI |
|--------|------------------------|------------|
| 调用方式 | HTTP POST /v1/messages | 命令行子进程 |
| 认证 | API Key (ANTHROPIC_API_KEY) | 本地登录态 |
| 适合场景 | 生产服务、高并发 | 开发调试、Agent 编排 |
| Tool Use | API 原生支持 | CLI 内置 + 自定义 MCP |
| 文件访问 | 需手动读取传入 | 内置 Read/Write/Bash 工具 |

**本项目选择 Claude CLI 的原因：**

1. **Agent 需要文件系统能力** — Bug 修复工作流需要 Claude 直接读写代码文件、运行测试，这些是 CLI 内置的
2. **MCP 集成** — 通过 `--mcp-config` 加载 Jira 等外部工具，无需自己实现 Tool 协议
3. **开发者体验** — 一行命令即可调用，无需管理 API Key 和 SDK 依赖

### 1.2 输出格式：json vs stream-json

Claude CLI 支持三种 `--output-format`：

#### `json` 模式（Oneshot）

```bash
claude -p "你好" --output-format json
```

返回一次性 JSON 对象：

```json
{
  "result": "你好！有什么可以帮助你的吗？",
  "is_error": false,
  "usage": {
    "input_tokens": 12,
    "output_tokens": 28
  }
}
```

**特点**：
- 一次返回完整结果，适合短任务
- `result` 字段包含最终文本
- `usage` 提供 token 计量

#### `stream-json` 模式（Streaming）

```bash
claude -p "修复这个 bug" --output-format stream-json --verbose
```

返回逐行 NDJSON（Newline-Delimited JSON），每行是一个事件：

```jsonl
{"type": "assistant", "message": {"content": [{"type": "thinking", "thinking": "让我分析..."}]}}
{"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Read", "input": {"file_path": "..."}}]}}
{"type": "user", "message": {"content": [{"type": "tool_result", "content": "文件内容..."}]}}
{"type": "assistant", "message": {"content": [{"type": "text", "text": "已修复。"}]}}
{"type": "result", "result": "已修复。", "usage": {...}, "total_cost_usd": 0.05}
```

**关键事件类型**：

| type | 含义 | 关键字段 |
|------|------|----------|
| `assistant` | Claude 的回复 | `message.content[]` — 可含 thinking/tool_use/text |
| `user` | 工具执行结果 | `message.content[]` — 含 tool_result |
| `result` | 最终结果 | `result`（文本）、`usage`、`total_cost_usd` |

**特点**：
- 实时流式输出，可边执行边展示
- 能看到 Claude 的思考过程和工具调用
- `result` 事件只包含**最后一条** assistant 文本（这是一个重要陷阱，后面 S3 详述）

#### `text` 模式

```bash
claude -p "你好" --output-format text
```

直接返回纯文本，无 JSON 包装。最简单但缺少元信息。

### 1.3 项目中的统一封装：claude_cli_wrapper.py

> 源码：`backend/workflow/claude_cli_wrapper.py`

在 M25 之前，项目中 Claude CLI 调用散落在多个文件中（agents/claude.py、nodes/llm_utils.py），存在重复的 env 清理、重试逻辑、错误处理。M25/T136 统一为两个入口函数：

```
claude_cli_wrapper.py
├── invoke_oneshot()   ← json 模式，单次调用 + 重试
├── invoke_stream()    ← stream-json 模式，流式事件回调
├── build_cli_args()   ← CLI 参数构建（共享）
├── clean_env()        ← 环境变量清理
├── ClaudeEvent        ← 结构化事件类型
└── 辅助函数
    ├── is_rate_limit_error()
    ├── extract_token_usage()
    ├── extract_result_text()
    └── resolve_screenshot()
```

**环境变量清理**（第 36-38 行）：

```python
def clean_env() -> Dict[str, str]:
    """Inherit env but remove CLAUDECODE to avoid nested session detection."""
    return {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}
```

为什么要删除 `CLAUDECODE`？因为我们的后端本身运行在 Claude Code 环境中（CCCC peer），如果子进程继承了 `CLAUDECODE` 环境变量，Claude CLI 会认为自己在嵌套 session 中，可能产生意外行为。

### 1.4 Oneshot 模式详解

> 源码：`claude_cli_wrapper.py:215-354`，调用方：`nodes/llm_utils.py`

```python
async def invoke_oneshot(
    *,
    prompt: str,          # 完整 prompt（system + user 已拼接）
    model: str = "",      # 模型名，空则用默认
    timeout: float = 300.0,
    max_retries: int = 2,
    retry_base_delay: float = 10.0,
    screenshot_path: str = "",
    allowed_tools: Optional[List[str]] = None,
    no_tools: bool = False,
    component_name: str = "unknown",  # 用于日志标识
) -> Dict[str, Any]:
    # 返回 {"text": str, "token_usage": dict|None, "retry_count": int, "duration_ms": int}
```

**调用链路**：

```
SpecAnalyzerNode
  → llm_utils.invoke_claude_cli(system_prompt=..., user_prompt=...)
    → claude_cli_wrapper.invoke_oneshot(prompt=system+user)
      → asyncio.create_subprocess_exec("claude", "-p", prompt, "--output-format", "json")
```

**重试机制**（指数退避 + 抖动）：

```python
for attempt in range(attempts):    # attempts = 1 + max_retries = 3
    if attempt > 0:
        base = retry_base_delay * (2 ** (attempt - 1))  # 10s, 20s
        if _is_rate_limited:
            base = max(base, 30.0)                       # rate limit 至少等 30s
        delay = base * (1.0 + random.uniform(-0.25, 0.25))  # ±25% 抖动
        await asyncio.sleep(delay)
    # ... 执行 CLI 调用
```

为什么需要抖动（jitter）？当多个 worker 同时触发 rate limit，如果都用固定延迟重试，会产生"惊群"效应——所有请求同时重试又同时被拒。抖动让重试时间分散开来。

**Rate limit 检测**：

```python
_RATE_LIMIT_PATTERNS = ("rate", "429", "overloaded", "too many", "throttl")

def is_rate_limit_error(error_msg: str) -> bool:
    lower = error_msg.lower()
    return any(p in lower for p in _RATE_LIMIT_PATTERNS)
```

### 1.5 Stream 模式详解

> 源码：`claude_cli_wrapper.py:361-489`，调用方：`nodes/agents.py`

```python
async def invoke_stream(
    prompt: str,
    cwd: str = ".",               # 工作目录（Bug 修复时是代码仓库路径）
    timeout: float = 300.0,
    on_event: Optional[Callable[[ClaudeEvent], None]] = None,  # 事件回调
) -> str:
```

**事件回调机制**：

```python
# 调用方注册回调，每收到一个事件就同步调用（非 async）
def my_callback(event: ClaudeEvent):
    if event.type == ClaudeEvent.THINKING:
        print(f"[思考] {event.content[:100]}")
    elif event.type == ClaudeEvent.TOOL_USE:
        print(f"[工具] {event.tool_name}: {event.content[:200]}")
    elif event.type == ClaudeEvent.TEXT:
        print(f"[输出] {event.content}")
    elif event.type == ClaudeEvent.RESULT:
        print(f"[完成] cost=${event.cost_usd}, tokens={event.usage}")

result = await invoke_stream(prompt, on_event=my_callback)
```

**实际使用场景**（Batch Bug Fix 工作流）：

在 `agents.py` 的 `LLMAgentNode` 中，`on_event` 回调会将事件推送到前端 SSE：

```python
# agents.py:135 简化示例（基于 _make_sse_event_callback）
def _make_sse_event_callback(inputs, node_id):
    """只推送重要工具调用，过滤掉探索性操作"""
    _IMPORTANT_TOOLS = frozenset({"edit", "write", "bash", "execute", "shell"})

    def callback(event: ClaudeEvent):
        if event.type == ClaudeEvent.TOOL_USE:
            if event.tool_name.lower() in _IMPORTANT_TOOLS:
                push_fn(job_id, "ai_thinking", {
                    "tool": event.tool_name,
                    "detail": event.content[:200],
                })
            # Read/Grep/Glob 等探索工具 → 静默忽略（每 20 次汇总一条）
        elif event.type == ClaudeEvent.RESULT:
            push_fn(job_id, "ai_thinking", {"text": event.content})

    return callback
```

### 1.6 System Prompt 的拼接方式

本项目中 system prompt 和 user prompt 是拼接后传入的，不使用 Claude API 的原生 `system` 参数：

```python
# llm_utils.py:41
full_prompt = f"{system_prompt}\n\n{user_prompt}"
```

**为什么不用 --system-prompt flag？**

Claude CLI 的 `-p` 参数接受整个 prompt，内部会作为 user message 发送。项目选择在 prompt 文本内部组织 system/user 分区，而不是使用 `--system-prompt` flag。这样更简单，且对于 Oneshot 模式（无多轮对话）效果等价。

---

## S2: Tool Use 实战指南

### 2.1 什么是 Tool Use

Claude 的 Tool Use 能力让模型可以调用外部工具来完成任务。在 Claude CLI 中，内置了大量工具：

| 工具类别 | 工具名 | 功能 |
|----------|--------|------|
| 文件读取 | Read | 读取文件内容 |
| 文件写入 | Write | 创建/覆盖文件 |
| 文件编辑 | Edit | 精确文本替换 |
| 搜索 | Grep, Glob | 内容搜索、文件名匹配 |
| 终端 | Bash | 执行 shell 命令 |
| 子任务 | Task | 启动子 agent |

当你给 Claude 一个任务（如"修复这个 bug"），它会自主决定：
1. 先用 Read 读取相关文件
2. 用 Grep 搜索错误来源
3. 用 Edit 修改代码
4. 用 Bash 运行测试验证

每次工具调用都会在 stream-json 中产生 `tool_use` 事件。

### 2.2 --allowedTools 精确控制

```python
# claude_cli_wrapper.py:68-69
if allowed_tools:
    args.extend(["--allowedTools"] + allowed_tools)
```

`--allowedTools` 是一个**白名单**，只允许 Claude 使用指定的工具。

**项目中的用法**（SpecAnalyzer Pass 1）：

```python
# llm_utils.py:44
allowed_tools = ["Read"] if screenshot_path else None
```

当有截图时，只允许 `Read` 工具——因为 Claude 需要读取截图文件来做视觉分析，但不需要其他工具（Write、Bash 等）。这样做的好处：

1. **节省 token** — 不注入不需要的工具定义
2. **防止意外操作** — 分析阶段不应修改文件
3. **加速响应** — 工具选择空间更小，模型决策更快

### 2.3 --tools "" 完全禁用工具

```python
# claude_cli_wrapper.py:70-71
elif no_tools:
    args.extend(["--tools", ""])
```

当不需要任何工具时（如 Pass 2 纯 JSON 提取），传入空字符串完全禁用 Tool Use。这让 Claude 只能输出文本，不会尝试调用任何工具。

### 2.4 项目中的三种 Tool 策略

| 场景 | Tool 策略 | 原因 |
|------|-----------|------|
| SpecAnalyzer Pass 1（截图分析）| `--allowedTools Read` | 只需读截图，不能写文件 |
| SpecAnalyzer Pass 2（JSON 提取）| `--tools ""` | 纯文本输出，无需任何工具 |
| Bug Fix Agent（代码修复）| 不限制（全部工具）| 需要读写文件、运行命令 |

**决策流程图**：

```
需要 Claude 修改文件系统？
  ├─ 是 → 不限制工具（Bug Fix、Code Gen）
  └─ 否 → 需要读取文件/截图？
           ├─ 是 → --allowedTools Read
           └─ 否 → --tools ""（纯文本输出）
```

### 2.5 Tool Use 事件解析

> 源码：`claude_cli_wrapper.py:176-208`

stream-json 模式下，Claude 的工具调用会产生多种事件。`_parse_assistant_content()` 函数解析这些事件：

```python
def _parse_assistant_content(content_blocks: list) -> list[ClaudeEvent]:
    events = []
    for block in content_blocks:
        block_type = block.get("type", "")
        if block_type == "thinking":
            # Claude 的内部思考（Extended Thinking 功能）
            events.append(ClaudeEvent(type=ClaudeEvent.THINKING, content=...))
        elif block_type == "tool_use":
            # 工具调用请求
            events.append(ClaudeEvent(
                type=ClaudeEvent.TOOL_USE,
                tool_name=block.get("name", "unknown"),
                tool_input=block.get("input", {}),
            ))
        elif block_type == "text":
            # 纯文本输出
            events.append(ClaudeEvent(type=ClaudeEvent.TEXT, content=...))
    return events
```

**一次典型的 Bug 修复流，事件序列**：

```
1. [thinking]  "让我先看看这个 bug 的上下文..."
2. [tool_use]  Read: {"file_path": "app/routes/design.py"}
3. [tool_result] "文件内容..."
4. [thinking]  "问题在第 42 行，缺少空值检查..."
5. [tool_use]  Edit: {"file_path": "app/routes/design.py", "old_string": "...", "new_string": "..."}
6. [tool_result] "编辑成功"
7. [tool_use]  Bash: {"command": "pytest tests/"}
8. [tool_result] "6 passed"
9. [text]      "已修复。问题是..."
10. [result]    "已修复。问题是..."  ← 最终结果
```

---

## S3: Prompt 踩坑集锦

### 3.1 Write 工具 vs 文本输出：result 只含最后一条 assistant text

**问题**：

当你让 Claude 生成代码并通过 stream-json 获取结果时，`result` 事件只包含**最后一条 assistant 文本消息**。如果 Claude 使用了 `Write` 工具写文件，最后一条消息通常是总结性的文字（如"组件已写入 Hero.tsx"），**而不是代码本身**。

**真实案例**：

```python
# 你期望 result 包含代码：
prompt = "生成一个 Hero 组件的 React 代码"
result = await invoke_oneshot(prompt=prompt)
code = extract_code_block(result["text"])
# ❌ result["text"] = "我已经将 Hero 组件写入了 Hero.tsx 文件。"
# extract_code_block() 找不到 ```tsx 代码块 → 返回原始文本
```

**解决方案 1：Prompt 约束输出方式**

```python
# ✅ 在 prompt 中明确要求
prompt = """生成一个 Hero 组件的 React 代码。

重要：直接在回复中输出代码，不要使用 Write 工具。
只输出代码，不要解释。"""
```

项目中 PageSkeleton 生成之所以正常工作，就是因为 prompt 说了"只输出代码，不要解释"，Claude 选择了直接输出代码文本。

**解决方案 2：--allowedTools 限制**

```python
# ✅ 不给 Write 工具，Claude 只能输出文本
result = await invoke_oneshot(
    prompt=prompt,
    allowed_tools=[],  # 或 no_tools=True
)
```

**教训**：永远不要假设 `result` 包含你想要的内容。当你需要代码文本时，必须通过 prompt 或 tool 限制来确保 Claude 直接输出，而不是写文件。

### 3.2 中文引号 vs JSON 引号冲突

**问题**：

当 prompt 中包含中文内容，且要求 JSON 输出时，Claude 有时会在 JSON 字符串值中使用中文引号（`""`、`「」`、`『』`），导致 JSON 解析失败。

**真实案例**：

```json
{
  "description": "这是一个「导航栏」组件"
}
```

Python 的 `json.loads()` 会失败，因为 `「」` 不是合法的 JSON 引号。

**解决方案**：在 JSON 解析前做引号替换。

```python
# llm_utils.py:83-86 — 项目中的实际处理
text = text.replace("\u201c", '"').replace("\u201d", '"')  # "" → "
text = text.replace("\u2018", "'").replace("\u2019", "'")  # '' → '
text = text.replace("\u300c", '"').replace("\u300d", '"')  # 「」→ "
text = text.replace("\u300e", '"').replace("\u300f", '"')  # 『』→ "
```

**另一个场景**：在 JSON 模板字符串中使用中文引号。

```python
# ❌ 错误：JSON 值内的中文引号会破坏结构
template = '{"prompt": "请分析这个"组件"的功能"}'

# ✅ 正确：使用「」代替""
template = '{"prompt": "请分析这个「组件」的功能"}'
# 解析时「」会被 sanitize 替换为 "
```

### 3.3 JSON 输出的 5 级恢复链

> 源码：`nodes/llm_utils.py:132-191`

LLM 输出的 JSON 经常不够干净——可能带 markdown 代码块、有尾部逗号、被截断等。项目实现了 5 级渐进式恢复：

```python
def parse_llm_json(raw: str) -> Optional[Dict]:
    """5 级 JSON 解析恢复链"""

    # Level 1: 直接解析
    json.loads(text)

    # Level 2: 去掉 markdown 代码块头尾
    # ```json\n{...}\n``` → {...}
    lines = text.split("\n")[1:-1]  # 去掉首尾 ``` 行

    # Level 3: 正则提取代码块
    re.search(r"```(?:json)?\s*\n(.*?)\n```", text, re.DOTALL)

    # Level 4: 清洗 + 重试
    _sanitize_llm_json(text)
    #   → 去控制字符
    #   → 中文引号 → ASCII 引号
    #   → 去尾部逗号 (,} → })
    #   → 自动闭合截断的 JSON（计算未匹配的 { [ 并补上 } ]）

    # Level 5: 提取最外层 { ... } + 清洗
    brace_start = sanitized.find("{")
    brace_end = sanitized.rfind("}")
    extracted = sanitized[brace_start:brace_end + 1]
```

**自动闭合截断 JSON** 是最巧妙的修复：

```python
# llm_utils.py:96-121（简化版，省略了反斜杠转义处理）
# 注：实际代码还处理了 \\ 转义（escape 标志位），防止 \" 转义引号误判 in_string 状态
in_string = False
stack = []
for ch in text:
    if ch == '"': in_string = not in_string
    if not in_string:
        if ch in ("{", "["): stack.append(ch)
        elif ch == "}" and stack[-1] == "{": stack.pop()
        elif ch == "]" and stack[-1] == "[": stack.pop()
# stack 中剩余的就是未闭合的括号
for opener in reversed(stack):
    text += "}" if opener == "{" else "]"
```

当 Claude 的响应因 token 限制被截断时，JSON 可能只有前半部分。这个算法扫描括号配对，自动补上缺失的闭合括号。

### 3.4 Two-Pass 架构：为什么要分两步

> 源码：`spec/spec_analyzer_prompt.py`

SpecAnalyzer 使用 Two-Pass 架构来分析 UI 组件：

```
Pass 1: 截图 + 结构化数据 → 自由文本分析（中文 markdown）
Pass 2: Pass 1 的分析文本 → 小型 JSON 元数据
```

**为什么不一步到位？**

1. **质量更高** — Pass 1 不受 JSON 格式约束，可以自由发挥分析能力。让模型"用自然语言思考"比直接要求 JSON 输出的质量明显更好
2. **解析更可靠** — Pass 2 的 JSON 很小（<50 行），解析失败的概率极低
3. **关注点分离** — Pass 1 用 screenshot（多模态），需要 Read 工具；Pass 2 纯文本，不需要任何工具
4. **调试更容易** — 出问题时可以单独检查每一步的输入输出

**Pass 1 Prompt 的关键设计**：

```python
PASS1_SYSTEM_PROMPT = """\
You are a senior UI/UX design analyst...

## Output Format
Write your analysis as **natural text in Chinese (中文)**. Use markdown formatting...
Do NOT output JSON. Do NOT wrap your response in code fences.
```

注意"Do NOT output JSON"这条约束——这是在明确告诉模型输出格式，防止它自作主张输出 JSON。

**Pass 2 Prompt 的关键设计**：

```python
PASS2_SYSTEM_PROMPT = """\
Your output must be a **single, valid JSON object** — nothing else.
No markdown, no explanation, no code fences, no preamble, no trailing text.
The first character of your response must be `{` and the last must be `}`.
```

三重约束（no markdown, no explanation, 首字符必须是 `{`）确保输出干净的 JSON。

### 3.5 Prompt 中的输出约束心法

从项目真实 prompt 中总结的模式：

#### 模式 1: 要自由文本 → 明确禁止 JSON

```
Write your analysis as natural text in Chinese (中文).
Do NOT output JSON. Do NOT wrap your response in code fences.
```

#### 模式 2: 要 JSON → 三重约束

```
Your output must be a single, valid JSON object — nothing else.
No markdown, no explanation, no code fences, no preamble, no trailing text.
The first character of your response must be `{` and the last must be `}`.
```

#### 模式 3: 要代码 → 禁止 Write 工具

```
直接在回复中输出代码，不要使用 Write 工具。
只输出代码，不要解释。
```

#### 模式 4: 定义输出 Schema

在 prompt 中直接给出 JSON Schema 示例，并注明每个字段的含义和约束：

```
### JSON Schema
{
  "role": "<page|section|container|...>",    // 枚举值，有限选择
  "suggested_name": "<PascalCase>",           // 格式约束
  "description": "<1-2 sentence Chinese>",    // 语言 + 长度约束
}
```

#### 模式 5: 用角色设定引导风格

```
You are a senior UI/UX design analyst. Your job is to examine...
```

```
You are a metadata extraction assistant. Given...
```

角色设定不是玄学——它建立了输出质量的基线预期。"senior analyst"比"assistant"产出更专业、更结构化的分析。

### 3.6 截图传递：多模态分析

Claude CLI 本身不直接支持图片参数，项目通过一个巧妙的方式实现截图传递：

```python
# claude_cli_wrapper.py:243-249
if screenshot_abs:
    full_prompt = (
        f"{prompt}\n\n"
        f"First, read the screenshot image at: {screenshot_abs}\n"
        "Use this screenshot as visual reference for your analysis."
    )
    tools = allowed_tools or ["Read"]  # 必须给 Read 工具
```

**原理**：在 prompt 中告诉 Claude 截图的文件路径，Claude 会用内置的 `Read` 工具读取图片。Claude Code 的 Read 工具支持读取图片文件（PNG、JPG 等），读取后 Claude 可以对图像内容做视觉分析。

**注意事项**：
1. 截图路径必须是**绝对路径**，相对路径可能因 cwd 不同而找不到文件
2. 必须允许 `Read` 工具，否则 Claude 无法读取截图
3. `resolve_screenshot()` 函数负责路径解析和存在性检查

### 3.7 重试与错误反馈

> 源码：`nodes/spec_analyzer.py:256` — `_retry_with_error_feedback()` 方法

当 Pass 2 的 JSON 解析失败时，SpecAnalyzer 会进行带错误反馈的重试：

```python
# 基于 spec_analyzer.py:256 _retry_with_error_feedback() 简化
result = await invoke_claude_cli(
    system_prompt=PASS2_SYSTEM_PROMPT,
    user_prompt=pass2_prompt,
)

parsed = parse_llm_json(result["text"])
if parsed is None:
    # 构造错误反馈 prompt
    retry_prompt = f"""你的上一次输出无法被解析为合法 JSON。

错误信息: JSONDecodeError at line 15
你的原始输出:
{result["text"][:1000]}

请重新输出，严格遵守 JSON 格式。首字符必须是 {{，末字符必须是 }}。"""

    result = await invoke_claude_cli(
        system_prompt=PASS2_SYSTEM_PROMPT,
        user_prompt=retry_prompt,
    )
    parsed = parse_llm_json(result["text"])
```

**关键设计**：
1. 把错误信息和原始输出都反馈给 Claude，让它知道哪里出了问题
2. 重试时不需要截图（Pass 2 不依赖截图）
3. 只重试一次——如果两次都失败，说明 prompt 或数据有根本问题

---

## 关键文件索引

```
backend/workflow/
├── claude_cli_wrapper.py    ← 统一 CLI 封装（invoke_oneshot, invoke_stream）
├── config.py                ← CLAUDE_CLI_PATH, CLAUDE_SKIP_PERMISSIONS 等配置
├── nodes/
│   ├── llm_utils.py         ← invoke_claude_cli 桥接 + JSON 解析恢复链
│   ├── spec_analyzer.py     ← SpecAnalyzer Two-Pass 实现
│   └── agents.py            ← LLMAgentNode, VerifyNode（stream 模式调用）
└── spec/
    ├── spec_analyzer_prompt.py  ← Pass 1/Pass 2 system + user prompt 模板
    └── codegen_prompt.py        ← CodeGen prompt 模板 + tech stack 配置
```

## 练习建议

### 练习 1: 体验两种输出模式

```bash
# Oneshot (json)
claude -p "用一句话解释 Python 的 GIL" --output-format json | python3 -m json.tool

# Streaming (stream-json)
claude -p "用一句话解释 Python 的 GIL" --output-format stream-json --verbose
```

观察两种模式的输出差异。

### 练习 2: Tool Use 限制实验

```bash
# 全工具 — Claude 可能会创建文件
claude -p "生成一个 Python hello world 程序"

# 只读 — Claude 只能输出文本
claude -p "生成一个 Python hello world 程序" --allowedTools Read

# 无工具 — Claude 纯文本回答
claude -p "生成一个 Python hello world 程序" --tools ""
```

对比三种模式下 Claude 的行为差异。

### 练习 3: 走读源码

1. 打开 `claude_cli_wrapper.py`，跟踪 `invoke_oneshot()` 的完整执行路径
2. 打开 `llm_utils.py`，在 `_sanitize_llm_json()` 中构造一个截断 JSON，手动模拟恢复过程
3. 打开 `spec_analyzer_prompt.py`，比较 Pass 1 和 Pass 2 的 prompt 设计差异

### 练习 4: 写一个自己的 Prompt

尝试设计一个 prompt，让 Claude 分析一段代码并输出 JSON 格式的分析结果。要求：
- 定义明确的输出 Schema
- 使用 Three-Fence 约束（no markdown, no explanation, 首字符 `{`）
- 实现一个简单的 JSON 解析 + 恢复函数

---

> 作者: superpowers-peer | 任务: T165 | 里程碑: M31
