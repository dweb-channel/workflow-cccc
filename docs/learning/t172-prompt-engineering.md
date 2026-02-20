# T172: Prompt Engineering 进阶 — 从模板到管线

> **前置**: T164（架构全景）、T165（Claude API 调用）、T171（Temporal 持久化工作流）
> **目标**: 掌握多 Pass LLM 管线设计、结构化输出约束、多模态 Prompt 工程实践
> **核心源码**:
> - `backend/workflow/spec/spec_analyzer_prompt.py` — Two-Pass 提示词模板（317 行）
> - `backend/workflow/spec/codegen_prompt.py` — CodeGen 提示词模板（211 行）
> - `backend/workflow/nodes/spec_analyzer.py` — SpecAnalyzerNode 执行链（462 行）
> - `backend/workflow/nodes/llm_utils.py` — JSON 解析与 CLI 调用（197 行）
> - `backend/workflow/spec/spec_merger.py` — LLM 输出合并（391 行）
> - `backend/workflow/claude_cli_wrapper.py` — 统一 CLI 封装（489 行）

---

## S1: Two-Pass 管线深度剖析

### 1.1 为什么要两趟，而不是一趟？

SpecAnalyzer 最初是单趟设计：截图 + 结构化数据 → 一次性返回完整 JSON。但在实践中遇到两个核心问题：

| 问题 | 表现 | 根因 |
|------|------|------|
| **JSON 解析失败率高** | 复杂组件的 JSON 经常 400+ 行，括号嵌套深，LLM 容易产生不完整 JSON | LLM 需要同时「理解设计」+「组织 JSON 结构」，认知负担过重 |
| **design_analysis 质量差** | 自由文本被塞进 JSON 字符串值里，换行/引号必须转义，LLM 倾向于写短 | JSON 格式约束限制了 LLM 的表达自由度 |

**Two-Pass 解法**的核心哲学：**让每一趟只做一件事**。

```
┌─────────────────────────────────────────────────────────┐
│ Pass 1 (发散)                                           │
│ 输入: 截图 + 结构化 spec                                 │
│ 输出: 自由格式的中文 Markdown (200-500 词)               │
│ 特点: 有截图视觉参考，无 JSON 约束，鼓励详尽分析         │
│ 目的: 产出产品核心资产 — design_analysis                 │
├─────────────────────────────────────────────────────────┤
│ Pass 2 (收敛)                                           │
│ 输入: Pass 1 分析文本 + 结构化 spec (无截图)            │
│ 输出: < 50 行的紧凑 JSON (role, name, interaction...)   │
│ 特点: 无截图(省 token)，纯文本→JSON 提取，低解析失败率   │
│ 目的: 提取结构化元数据，供下游代码生成使用                │
└─────────────────────────────────────────────────────────┘
```

> **关键洞察**: Pass 1 的 `design_analysis` 是产品核心输出，永远不会被序列化为 JSON 字符串值。它直接以 Markdown 文本形式存储在 ComponentSpec 上。见 `spec_analyzer.py:450`:
> ```python
> # Inject design_analysis from Pass 1 directly (never serialized as JSON)
> analyzer_output["design_analysis"] = design_analysis_text
> ```

### 1.2 Pass 1: 发散式设计分析

**源码**: `spec_analyzer_prompt.py:17-157`

#### System Prompt 设计策略

Pass 1 的 System Prompt 有 127 行，是整个项目最长的单个提示词。设计策略：

**1) 角色设定 — 高级设计师**
```python
# spec_analyzer_prompt.py:18-21
PASS1_SYSTEM_PROMPT = """\
You are a senior UI/UX design analyst. Your job is to examine a UI component \
screenshot alongside its structural data and write a comprehensive design \
handoff analysis — like the explanation a senior designer would give a \
developer during a design review.
```

角色选择 "senior designer giving a design review" 而非 "AI assistant"，引导 LLM 产出专业级分析。

**2) 输出格式 — 显式排除 JSON**
```python
# spec_analyzer_prompt.py:25-27
Write your analysis as **natural text in Chinese (中文)**. Use markdown \
formatting (headers, bullet points, bold) for readability. Do NOT output JSON. \
Do NOT wrap your response in code fences.
```

三重否定约束（"Do NOT output JSON" + "Do NOT wrap in code fences" + "natural text"）确保 LLM 不会自作主张输出结构化数据。

**3) 19 种语义角色枚举表**

```python
# spec_analyzer_prompt.py:40-66
| Role | When to Use |
|------|------------|
| `page` | Root-level full-screen container |
| `section` | Major content region grouping related elements |
...
| `other` | LAST RESORT — re-check the 18 specific roles first |
```

这是一个 **constrained vocabulary** 策略：
- 完整枚举所有合法值 + 每个值的使用条件
- 末尾强调 "other" 是最后手段，引导 LLM 尽量匹配具体角色
- 同一张表在 Pass 1 和 Pass 2 中都出现，确保两趟的角色判定一致

**4) 10 个分析维度 — 有序但灵活**

```python
# spec_analyzer_prompt.py:34-35
Write naturally and thoroughly. Cover these aspects (in whatever order \
makes sense for this specific component):
```

关键技巧："in whatever order makes sense" — 给出结构化的分析维度清单，但不强制顺序。这让 LLM 可以根据组件特点自然地组织叙述，而不是机械填表。

10 个维度按重要性排列：
1. 组件概述与角色判定
2. 命名建议
3. 视觉状态与模式
4. 视觉层级
5. 布局策略
6. 关键样式值
7. 子元素分析（含 node ID 匹配）
8. 交互行为
9. 设计意图
10. 特殊标记

**5) 子元素分析 — 跨深度 + ID 回溯**

```python
# spec_analyzer_prompt.py:97-103
For each meaningful child element (at ALL depth levels — direct children, \
grandchildren, and deeper), describe:
- Its **ID** from the structural data (so it can be matched back)
- Its **role** (from the 19 roles above)
- A good **PascalCase name**
- What it does (brief description)
```

"at ALL depth levels" 强调递归遍历，"ID from the structural data" 要求引用原始数据中的 ID，让后续 `spec_merger.py` 可以精确匹配。

**6) 交互推断 — 基于视觉线索**

```python
# spec_analyzer_prompt.py:106-112
Infer interaction behaviors from visual cues and component role:
- Buttons always have click behavior
- Icons with tap targets (≥24px, in nav bar) likely have click
- Navigation elements (back arrow, close X): click → navigate
- Images in galleries: may have swipe
- Only describe plausible interactions — don't fabricate
```

这是一个 **guided inference** 策略：给出推断规则 + 反面约束（"don't fabricate"），让 LLM 在合理推断和幻觉之间找到平衡。

#### User Prompt 设计策略

```python
# spec_analyzer_prompt.py:129-156
PASS1_USER_PROMPT = """\
Analyze this UI component and write a comprehensive design analysis.

## Page Context
- Device: {device_type} ({device_width}×{device_height}px)
- Responsive strategy: {responsive_strategy}
- Page layout: {page_layout_type}
- Sibling components on this page: {sibling_names}

## Design Tokens
{design_tokens_json}

## Full ComponentSpec (structural fields filled recursively)
{partial_spec_json}
```

User Prompt 结构：**上下文 → 数据 → 指令**

- **Page Context**: 设备尺寸、布局类型、同级组件名。同级组件名让 LLM 知道页面全貌，产出更合理的命名
- **Design Tokens**: 全局设计变量（颜色、字体、间距等），让分析能引用 token 名
- **ComponentSpec**: 经过 `_strip_semantic_fields()` 处理的结构化数据（role/description/interaction 置为 null）
- 最后 5 条指令确保分析覆盖所有维度

**参数化模板**使用 Python `.format()` 而非 f-string，因为模板定义时变量尚不存在。填充发生在 `spec_analyzer.py:355-364`：

```python
# spec_analyzer.py:355-364
pass1_user = PASS1_USER_PROMPT.format(
    device_type=device.get("type", "mobile"),
    device_width=device.get("width", 393),
    device_height=device.get("height", 852),
    responsive_strategy=page.get("responsive_strategy", "fixed-width"),
    page_layout_type=page_layout.get("type", "flex"),
    sibling_names=sibling_names_str,
    design_tokens_json=tokens_json,
    partial_spec_json=partial_spec_json,
)
```

### 1.3 Pass 2: 收敛式元数据提取

**源码**: `spec_analyzer_prompt.py:162-236`

Pass 2 的设计目标完全不同：从 Pass 1 的自由文本中提取结构化 JSON。

#### System Prompt 关键差异

| 维度 | Pass 1 | Pass 2 |
|------|--------|--------|
| 角色 | senior UI/UX design analyst | metadata extraction assistant |
| 输入 | 截图 + 结构化 spec | Pass 1 文本 + 结构化 spec |
| 输出 | 中文 Markdown | JSON 对象 |
| 约束 | "Do NOT output JSON" | "first character must be `{` and last must be `}`" |
| 长度 | 200-500 词 | < 50 行 |

```python
# spec_analyzer_prompt.py:167-169
Your output must be a **single, valid JSON object** — nothing else. \
No markdown, no explanation, no code fences, no preamble, no trailing text. \
The first character of your response must be `{` and the last must be `}`.
```

**五重否定约束**: No markdown, no explanation, no code fences, no preamble, no trailing text。加上首末字符约束 `{` ... `}`，最大限度确保输出是纯 JSON。

#### JSON Schema 显式定义

```python
# spec_analyzer_prompt.py:173-195
### JSON Schema
{
  "role": "<page|section|...|other>",
  "suggested_name": "<PascalCase, e.g. HeroBanner>",
  "description": "<1-2 sentence Chinese description>",
  "render_hint": "<full|spacer|platform|null>",
  "content_updates": { "image_alt": "<...>", "icon_name": "<...>" },
  "interaction": { "behaviors": [...], "states": [...] },
  "children_updates": [
    {"id": "<exact node ID from spec>", "role": "...", "suggested_name": "...", "description": "..."}
  ]
}
```

Schema 设计策略：
- **字段精简**: 只有 7 个顶层字段，`design_analysis` 故意排除（"Do NOT include"）
- **Enum 约束**: `role` 列出所有合法值，`trigger` 列出 6 种类型
- **children_updates 扁平化**: 所有深度的子元素放在同一个数组里（"FLAT — no nesting"），降低 JSON 嵌套深度

#### User Prompt — 从 Pass 1 到 Pass 2 的桥接

```python
# spec_analyzer_prompt.py:216-236
PASS2_USER_PROMPT = """\
Extract structured metadata from the following design analysis.

## Design Analysis (from previous analysis pass)
{design_analysis_text}

## Page Context
- Sibling components: {sibling_names}

## ComponentSpec (structural data with node IDs for children_updates matching)
{partial_spec_json}
```

注意 Pass 2 不包含截图。这是刻意的设计：
- **省 token**: 截图是 token 消耗大户，Pass 2 不需要视觉信息
- **聚焦提取**: 所有视觉信息已在 Pass 1 文本中被文字化，Pass 2 只做文本→JSON

### 1.4 输出验证 Schema

```python
# spec_analyzer_prompt.py:240-311
PASS2_OUTPUT_SCHEMA = {
    "type": "object",
    "required": ["role", "description"],
    "properties": {
        "role": {
            "type": "string",
            "enum": [
                "page", "section", "container", "card", "list", "list-item",
                "nav", "header", "footer", "button", "input", "image", "icon",
                "text", "divider", "badge", "overlay", "decorative", "other",
            ],
        },
        ...
    },
}
```

`PASS2_OUTPUT_SCHEMA` 当前定义了完整的 JSON Schema，但注意 `required` 只有 `["role", "description"]` — 这是一个 **宽松验证** 策略。原因：LLM 有时会省略空数组字段（如无交互时省略 `interaction`），如果 required 过严会导致大量误报。

---

## S2: CodeGen Prompt 设计

### 2.1 CodeGen vs SpecAnalyzer — 策略差异

`codegen_prompt.py`（211 行）负责 Phase 5（代码生成），与 SpecAnalyzer 的 Two-Pass 策略完全不同：

| 维度 | SpecAnalyzer (Two-Pass) | CodeGen (Single-Pass) |
|------|------------------------|----------------------|
| 趟数 | 2 趟（发散→收敛） | 1 趟 |
| 输入 | 截图 + 部分 spec | 截图 + 完整 spec |
| 输出 | 中文文本 + 小 JSON | 紧凑 JSON (component_name, file_name, code) |
| 目标 | 理解设计意图 | 产出可运行代码 |
| JSON 复杂度 | 高（需要 children_updates） | 低（code 是单个字符串） |

CodeGen 用单趟的原因：输出 JSON 只有 5 个字段，`code` 虽然长但是单个字符串值（无嵌套），解析失败率远低于 SpecAnalyzer 的 `children_updates` 嵌套数组。

### 2.2 Tech Stack 参数化

```python
# codegen_prompt.py:39-41
## Tech Stack: {tech_stack}

{tech_stack_guidelines}
```

```python
# codegen_prompt.py:127-138
TECH_STACKS = {
    "react-tailwind": {
        "name": "React + Tailwind CSS",
        "guidelines": CODEGEN_TECH_STACK_REACT_TAILWIND,
        "file_ext": "tsx",
    },
    "vue-tailwind": {
        "name": "Vue 3 + Tailwind CSS",
        "guidelines": CODEGEN_TECH_STACK_VUE_TAILWIND,
        "file_ext": "vue",
    },
}
```

**参数化 Tech Stack** 的好处：
- 同一套 System Prompt 适配多种技术栈，只替换 guidelines 片段
- `get_tech_stack_config()` 提供默认值回退（`codegen_prompt.py:141-143`）
- 新增技术栈只需添加一条字典记录 + guidelines 文本

#### React + Tailwind Guidelines 细节

```python
# codegen_prompt.py:73-85
CODEGEN_TECH_STACK_REACT_TAILWIND = """\
- Framework: React (functional components with hooks)
- Styling: Tailwind CSS utility classes
- File extension: .tsx (TypeScript)
- Export: `export default function ComponentName()`
- No CSS modules, no styled-components, no inline style objects
- Use Tailwind for ALL styling — colors, spacing, typography, layout, effects
- For values not in Tailwind's default scale, use arbitrary values: \
`w-[393px]`, `bg-[#1A1A1A99]`, `rounded-[100px]`
- For shadows, use arbitrary values: `shadow-[0_4px_10px_rgba(0,0,0,0.1)]`
- For backdrop blur: `backdrop-blur-[20px]`
- For gradients: use Tailwind gradient utilities or arbitrary values
"""
```

关键技巧：
- **排除法**: "No CSS modules, no styled-components, no inline style objects" — 明确列出不许用的替代方案
- **Arbitrary value 示例**: 给出具体语法 `w-[393px]`、`bg-[#1A1A1A99]`，因为 LLM 可能不熟悉 Tailwind 的任意值语法
- **阴影/模糊特殊语法**: 这些是 LLM 最容易出错的 Tailwind 特性，用示例预防

### 2.3 CodeGen System Prompt 11 条规则

```python
# codegen_prompt.py:44-71
## Code Quality Rules
1. **Match the screenshot exactly** — colors, spacing, typography, ...
2. **Use spec values directly** — don't approximate colors or sizes
3. **Responsive within component** — ...work at specified width but not hardcode
4. **Self-contained** — each component is a single file with no external dependencies
5. **Semantic HTML** — use appropriate HTML elements based on component role
6. **Interaction states** — implement hover/active/disabled states
7. **Click handlers** — add onClick/onPress handlers...Use console.log placeholders
8. **Accessibility** — include aria-labels, alt text
9. **No placeholder images** — use colored div with image dimensions
10. **Icons** — use text/emoji placeholders with comment noting icon name
11. **Collapsed children** — spec may include `children_collapsed: N`...
```

规则设计原则：
- **规则 1-2**: 精确度约束 — "don't approximate"，强制使用 spec 中的精确值
- **规则 4**: 隔离性约束 — "no external dependencies beyond tech stack"，确保每个组件可独立渲染
- **规则 7**: 占位行为 — `console.log` 作为交互占位符，而非空函数
- **规则 9-10**: 资源占位策略 — 图片用 colored div，图标用 emoji，都附注释说明真实资源
- **规则 11**: 降级处理 — `children_collapsed: N` 是 FrameDecomposer 深度裁剪的产物，提示 LLM 看截图补充

### 2.4 Sibling Context — 页面感知

```python
# codegen_prompt.py:166-210
def build_sibling_context(
    components: list,
    current_index: int,
) -> str:
    """Build a concise page context snippet showing sibling components.

    Format:
        Above: PageHeader (header, 393x92, y:0)
        Current: GalleryFilterBar ← generating this
        Below: PhotoGallery (section, flex row gap:4, 377x716, y:190)
    """
```

这个函数为 CodeGen 提供「页面上下文视图」：当前正在生成的组件 + 上方/下方的同级组件。格式精心设计：

```
  Above: PageHeader (header, 393x92, y:0)
  >> GalleryFilterBar (section, flex row gap:4, ...)  ← YOU ARE GENERATING THIS
  Below: PhotoGallery (section, flex row gap:4, 377x716, y:190)
```

每个同级组件用一行摘要：`name (role, layout_detail, WxH, y:N)`，信息密度高但可读。`>>` 箭头标记当前组件，视觉上一目了然。

### 2.5 CodeGen 与 SpecAnalyzer 的 Prompt 策略对比

| 策略 | SpecAnalyzer Pass 1 | SpecAnalyzer Pass 2 | CodeGen |
|------|---------------------|---------------------|---------|
| 角色扮演 | senior designer | metadata extractor | expert frontend developer |
| 输出格式 | free text | strict JSON | JSON with code string |
| 截图使用 | 有 | 无 | 有 |
| 语言 | 中文 | 中文 description + 英文字段 | 英文代码 |
| Enum 约束 | 19 roles | 19 roles + triggers | tech stack |
| 重试成本 | 低(文本不会失败) | 中(小JSON) | 高(整段代码重生成) |
| 模板变量 | 7 个 | 3 个 | 5 个 |

---

## S3: SpecAnalyzerNode 执行链

### 3.1 整体执行流

`spec_analyzer.py` 的 `_analyze_single_component` 方法（:321-461）实现了完整的 Two-Pass 执行链：

```
_strip_semantic_fields(component)    ← 清理输入
         │
         ▼
    Pass 1: invoke_claude_cli        ← 截图 + partial spec → design_analysis
         │
         ▼
    Pass 2: invoke_claude_cli        ← Pass 1 text + spec → JSON
         │
         ▼
    parse_llm_json(raw_pass2)        ← 多阶段 JSON 恢复
         │
    ┌────┴────┐
    │ 成功    │ 失败
    ▼         ▼
  merge    _retry_with_error_feedback ← 错误反馈重试
              │
         ┌────┴────┐
         │ 成功    │ 失败
         ▼         ▼
       merge    safe defaults         ← {role:"section", description:""}
         │
         ▼
    merge_analyzer_output(component, analyzer_output)  ← 合并到 ComponentSpec
         │
         ▼
    return merged + _token_usage + _retry_count + _duration_ms
```

### 3.2 输入清洗 — _strip_semantic_fields

```python
# spec_analyzer.py:36-54
def _strip_semantic_fields(spec: Dict) -> Dict:
    """Create a copy of ComponentSpec with semantic fields nulled out."""
    result = {}
    for key, value in spec.items():
        if key in ("role", "description", "render_hint"):
            result[key] = None  # LLM will fill these
        elif key == "interaction":
            result[key] = None
        elif key == "children":
            result[key] = [
                _strip_semantic_fields(c) if isinstance(c, dict) else c
                for c in value
            ]
        else:
            result[key] = value
    return result
```

这个函数做 **受控信息隔离**：
- 将语义字段（role, description, render_hint, interaction）置 null → LLM 看到 null 知道该填充什么
- **递归处理 children** → 确保子组件的语义字段也被清空
- **不修改原始输入** → 返回新字典，函数是纯的（测试验证：`test_does_not_mutate_input`）

### 3.3 并发控制 — Semaphore + Stagger

```python
# spec_analyzer.py:152-161
from ..settings import SPEC_CLI_CONCURRENCY, SPEC_COMPONENT_STAGGER_DELAY
sem = asyncio.Semaphore(SPEC_CLI_CONCURRENCY)  # = 3

async def _analyze_one(idx: int, component: Dict) -> Dict:
    # Stagger launches to avoid hitting rate limits
    if idx > 0:
        await asyncio.sleep(idx * SPEC_COMPONENT_STAGGER_DELAY)  # = 2.0s
    async with sem:
        ...
```

双层限流策略：
- **Semaphore(3)**: 同时最多 3 个 Claude CLI 进程
- **Stagger delay**: 每个组件启动间隔 `idx × 2.0s`，避免瞬间并发触发 API 限流

所有组件通过 `asyncio.gather` 并发执行：

```python
# spec_analyzer.py:225-228
raw_results = await asyncio.gather(
    *[_analyze_one(i, c) for i, c in enumerate(components)],
    return_exceptions=True,
)
```

`return_exceptions=True` 确保一个组件失败不会取消其他组件的分析。

### 3.4 Pass 1 调用 — 多模态截图分析

```python
# spec_analyzer.py:366-377
pass1_result = await _invoke_claude_cli(
    claude_bin=claude_bin,
    system_prompt=PASS1_SYSTEM_PROMPT,
    user_prompt=pass1_user,
    screenshot_path=component.get("screenshot_path", ""),  # ← 截图路径
    base_dir=cwd,
    model=model,
    timeout=300.0,       # 5 分钟超时（视觉分析较慢）
    max_retries=max_retries,
    component_name=f"{comp_name}_pass1",
    caller=f"SpecAnalyzerNode [{self.node_id}]",
)
```

截图如何注入 Claude CLI？看 `claude_cli_wrapper.py:242-249`：

```python
# claude_cli_wrapper.py:242-249
if screenshot_abs:
    full_prompt = (
        f"{prompt}\n\n"
        f"First, read the screenshot image at: {screenshot_abs}\n"
        "Use this screenshot as visual reference for your analysis."
    )
    tools = allowed_tools or ["Read"]
```

截图路径被编入 prompt 文本，然后通过 `--allowedTools Read` 让 Claude CLI 用 Read 工具读取图片。这是一种 **间接多模态** 策略 — 不直接传 base64，而是让 Claude 自行读取文件。

为什么不直接传 base64？因为 Claude CLI 的 `-p` 参数是纯文本，不支持内嵌二进制。通过 Read 工具，Claude 能用其内置的多模态能力处理图片。

### 3.5 Pass 2 调用 — 纯文本提取

```python
# spec_analyzer.py:397-407
pass2_result = await _invoke_claude_cli(
    claude_bin=claude_bin,
    system_prompt=PASS2_SYSTEM_PROMPT,
    user_prompt=pass2_user,
    base_dir=cwd,     # ← 无 screenshot_path
    model=model,
    timeout=120.0,     # 2 分钟（提取比分析快）
    max_retries=max_retries,
    component_name=f"{comp_name}_pass2",
    caller=f"SpecAnalyzerNode [{self.node_id}]",
)
```

关键差异：
- **无截图**: 省 token，Pass 1 文本已充分描述视觉信息
- **超时更短**: 120s vs 300s，因为纯文本提取比视觉分析快
- **`no_tools=True`**: 无截图时 `llm_utils.py:44-45` 自动设置 `no_tools=True`，禁用所有工具

### 3.6 JSON 解析恢复链 — parse_llm_json

`llm_utils.py:132-191` 的 `parse_llm_json` 是整个管线的关键防线，实现了 **五阶段渐进恢复**：

```python
# llm_utils.py:132-191 (简化)
def parse_llm_json(raw: str, caller: str = "LLM") -> Optional[Dict]:
    """Pipeline:
    1. Strip leading markdown fence (if any) ← 去除 ```json 前缀
    2. Direct parse                          ← 理想情况（含已剥离 fence 的文本）
    3. Regex extract from fence → parse      ← LLM 把 JSON 嵌在文本中间
    4. Sanitize → parse                      ← 中文引号、尾逗号、截断
    5. Extract outermost { ... } → sanitize → parse  ← 最后手段
    """
```

**阶段 1: 剥离 Markdown 代码块**（实际代码先于 direct parse 执行）
```python
if text.startswith("```"):
    lines = text.split("\n")
    lines = lines[1:]  # 去掉 ```json
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]  # 去掉结尾 ```
    text = "\n".join(lines).strip()
```

**阶段 2: 直接解析**（此时 text 已去除可能的 fence 前缀）
```python
try:
    return json.loads(text)
except json.JSONDecodeError:
    pass
```

**阶段 3: 正则提取非前置代码块**
```python
fence_match = re.search(r"```(?:json)?\s*\n(.*?)\n```", text, re.DOTALL)
```
处理 LLM 先输出一段说明文字、然后才给出 JSON 代码块的情况。

**阶段 4: _sanitize_llm_json**

这是最重要的修复层，处理 LLM JSON 的四类常见错误：

```python
# llm_utils.py:63-129
def _sanitize_llm_json(text: str, caller: str = "LLM") -> str:
    # 1. Strip control characters (keep \t \n \r)
    cleaned = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text)
    text = cleaned  # 后续阶段基于清理后的文本

    # 2. Replace Chinese/smart quotes with ASCII
    text = text.replace("\u201c", '"').replace("\u201d", '"')  # ""
    text = text.replace("\u300c", '"').replace("\u300d", '"')  # 「」

    # 3. Remove trailing commas before } or ]
    new_text = re.sub(r",\s*([}\]])", r"\1", text)

    # 4. Auto-close truncated JSON (unmatched { and [)
    in_string = False
    escape = False
    stack: list[str] = []
    for ch in text:
        if escape:
            escape = False
            continue
        if ch == "\\":
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch in ("{", "["):
            stack.append(ch)
        elif ch == "}" and stack and stack[-1] == "{":
            stack.pop()
        elif ch == "]" and stack and stack[-1] == "[":
            stack.pop()
    if stack:
        for opener in reversed(stack):
            text += "}" if opener == "{" else "]"
```

**自动闭合算法详解**：
- 用 `in_string` + `escape` 标志跟踪是否在字符串内部
- `escape` 标志处理 `\"` 转义字符 → 避免误判字符串边界（T165 审查发现的关键细节）
- 遇到 `{` / `[` 入栈，遇到 `}` / `]` 出栈
- 最后栈中剩余的未闭合括号，逆序补齐

**阶段 5: 提取 outermost { ... }**
```python
brace_start = sanitized.find("{")
brace_end = sanitized.rfind("}")
if brace_start >= 0 and brace_end > brace_start:
    extracted = sanitized[brace_start:brace_end + 1]
```

当 LLM 在 JSON 前后添加了解释文本时，提取最外层的花括号范围。

### 3.7 错误反馈重试 — _retry_with_error_feedback

当 `parse_llm_json` 所有阶段都失败时，启动错误反馈重试：

```python
# spec_analyzer.py:256-319
async def _retry_with_error_feedback(self, ...):
    # 获取具体的解析错误
    try:
        _json.loads(raw_text)
    except _json.JSONDecodeError as e:
        parse_error = str(e)

    # 截断原始输出（避免 token 溢出）
    truncated = raw_text[:3000] if len(raw_text) > 3000 else raw_text

    correction_prompt = (
        "Your previous response could not be parsed as valid JSON.\n\n"
        f"Parse error: {parse_error}\n\n"
        f"Your previous output (may be truncated):\n{truncated}\n\n"
        "Please return ONLY the corrected valid JSON object. "
        "Fix any escaping issues in string values "
        "(use \\n for newlines, \\\" for quotes inside strings)."
    )
```

策略：
- **具体错误信息**: 把 `JSONDecodeError` 的具体信息传给 LLM（如 "Expecting ',' delimiter: line 45 column 3"）
- **截断保护**: 原始输出截断到 3000 字符，避免重试 prompt 超长
- **转义提示**: 显式告诉 LLM 常见转义问题的修复方法
- **单次重试**: `max_retries=0`，不再递归重试
- **角色切换**: "You are a JSON repair assistant" — 不再是设计分析师，而是修 JSON 的

### 3.8 安全降级 — Safe Defaults

```python
# spec_analyzer.py:435-447
if not analyzer_output:
    # Pass 2 failed completely — preserve design_analysis from Pass 1
    logger.error(...)
    analyzer_output = {
        "role": "section",    # safe default
        "description": "",
        "suggested_name": comp_name,
    }

# Inject design_analysis from Pass 1 directly
analyzer_output["design_analysis"] = design_analysis_text
```

**关键设计**: 即使 Pass 2 完全失败，Pass 1 的 `design_analysis` 仍然被保留。这是 Two-Pass 架构的核心价值 — Pass 1 产出独立于 Pass 2，不会因 JSON 解析问题丢失。

### 3.9 Merge 管线 — spec_merger.py

`merge_analyzer_output`（`spec_merger.py:307-390`）负责将 LLM 输出合并回 ComponentSpec：

```python
def merge_analyzer_output(partial_spec, analyzer_output):
    result = deepcopy(partial_spec)  # 不修改输入

    # 1. 构建 children_updates 查找表
    children_map = _build_children_map(children_updates)  # O(1) 查找

    # 2. 合并顶层字段
    _merge_into_component(result, analyzer_output, children_map, report)

    # 3. 递归遍历所有子节点，匹配 children_updates
    # （已在 _merge_into_component 中调用 _walk_children_for_updates）

    # 4. 检测未匹配的 children_updates
    # 区分「被裁剪的」（预期行为）和「真正未匹配的」（可能是幻觉）

    # 5. 重建路径
    _rebuild_paths(result)

    # 6. 附加合并报告
    result["_merge_report"] = report.to_dict()
```

**三个关键设计决策**：

**决策 1: children_updates 扁平化 + 全树遍历**

LLM 返回扁平的 `children_updates` 数组，每个条目只有 `id` 标识。`_walk_children_for_updates`（:192-215）对组件树做全深度遍历匹配：

```python
def _walk_children_for_updates(node, children_map, report):
    children = node.get("children")
    for child in children:
        child_id = child.get("id")
        if child_id and child_id in children_map:
            _apply_update_fields(child, children_map[child_id], report)
        # Always recurse deeper
        _walk_children_for_updates(child, children_map, report)
```

"Always recurse deeper" — 即使当前节点没有更新，也继续深入。这确保了深层子节点（depth 3+）也能匹配。

**决策 2: 幻觉检测 — pruned vs unmatched**

```python
# spec_merger.py:341-351
all_child_ids: set = set()
_collect_all_child_ids(result, all_child_ids)
pruned_ids = set(_collect_all_pruned_ids(result))
for child_id in children_map:
    if child_id not in all_child_ids:
        if child_id in pruned_ids:
            report.children_updates_pruned.append(child_id)  # 预期: 被深度裁剪的
        else:
            report.children_updates_unmatched.append(child_id)  # 警告: 可能是幻觉
```

LLM 返回的 `children_updates` 中有些 ID 在组件树中找不到。区分两种情况：
- **Pruned**: FrameDecomposer 因深度限制裁剪掉的子节点，LLM 从截图中识别到了 → info 级日志
- **Unmatched**: 既不在树中也不在裁剪列表中 → warning 级日志，可能是 LLM 幻觉

**决策 3: 交互状态合并 — Node 1 + LLM**

```python
# spec_merger.py:83-132
def _merge_interaction(component, interaction):
    # Behaviors: LLM output replaces (Node 1 doesn't generate behaviors)
    # States: merge LLM descriptions with Node 1 style_overrides
    for llm_state in llm_states:
        if name in existing_by_name:
            merged = existing_by_name[name].copy()
            merged["description"] = llm_state["description"]  # LLM 补充描述
            # 保留 Node 1 的 style_overrides
```

Node 1 (FrameDecomposer) 从 Figma 数据中提取了交互状态的样式覆盖（hover 时背景变色等），但没有自然语言描述。LLM 补充描述，同时保留精确的样式数据。这是 **人机协作** 的典型模式：机器提供精确值，LLM 提供语义理解。

### 3.10 Token 追踪

整个执行链精确追踪 token 使用：

```python
# spec_analyzer.py:351, 381-383, 410-412
total_tokens: Dict[str, int] = {"input_tokens": 0, "output_tokens": 0}

# Pass 1 token accumulation
if pass1_result["token_usage"]:
    total_tokens["input_tokens"] += pass1_result["token_usage"].get("input_tokens", 0)
    total_tokens["output_tokens"] += pass1_result["token_usage"].get("output_tokens", 0)

# Pass 2 token accumulation (same pattern)
```

Token 数据通过 `_token_usage` 附加在返回值上，最终汇总到 `analysis_stats`，并通过 SSE 推送到前端。这让用户能实时看到每个组件的 token 消耗。

---

## S4: 动手练习

### 练习 1: 设计一个 Two-Pass Prompt（代码审查场景）

**场景**: 你需要用 LLM 审查一段 Python 代码，产出：
- Pass 1: 自由文本的代码审查报告（问题列表、改进建议、整体评价）
- Pass 2: 结构化 JSON（severity, category, line_number, suggestion）

**要求**:
1. 参考 `spec_analyzer_prompt.py` 的 Pass 1 / Pass 2 分离模式
2. Pass 1 System Prompt 要包含：角色设定、输出格式约束、分析维度清单
3. Pass 2 System Prompt 要包含：JSON Schema 定义、首末字符约束、字段枚举
4. 思考：Pass 1 是否需要传入代码文件？Pass 2 是否还需要传入代码？

**提示**:
```python
# 你的 Pass 1 System Prompt
CODE_REVIEW_PASS1_SYSTEM = """\
You are a senior Python developer conducting a code review...

## Output Format
Write your review as natural text in Chinese...

## Review Dimensions
1. 代码正确性
2. 性能隐患
3. 安全风险
4. 可读性与命名
5. 测试覆盖建议
"""

# 你的 Pass 2 System Prompt
CODE_REVIEW_PASS2_SYSTEM = """\
You are a structured data extraction assistant...
{
  "issues": [
    {"severity": "high|medium|low", "category": "...", "line": N, "suggestion": "..."}
  ],
  "overall_score": 1-10,
  "summary": "..."
}
"""
```

### 练习 2: parse_llm_json 恢复链实操

给定以下 LLM 「坏输出」，手动走一遍 `parse_llm_json` 的五阶段恢复链，判断每个阶段的结果：

**Case A**: 前置文本 + JSON
```
Here is the extracted metadata:
```json
{"role": "button", "suggested_name": "SubmitButton"}
```
```

**Case B**: 中文引号 + 尾逗号
```
{"role": "section", "description": "这是一个「导航栏」组件", "children_updates": [{"id": "1:1",},]}
```

**Case C**: 截断 JSON
```
{"role": "card", "children_updates": [{"id": "1:1", "role": "text"}, {"id": "1:2", "role"
```

**分析每个 Case**:
- 阶段 1 (fence 剥离) + 阶段 2 (直接解析) 成功/失败？
- 哪个阶段最终成功？
- `_sanitize_llm_json` 做了哪些修复？

### 练习 3: 为 CodeGen 添加新 Tech Stack

假设需要支持 **Svelte + Tailwind** 技术栈：

1. 在 `codegen_prompt.py` 中添加 `CODEGEN_TECH_STACK_SVELTE_TAILWIND` guidelines
2. 在 `TECH_STACKS` 字典中注册
3. 思考 Svelte 的单文件组件（`.svelte`）与 React 的函数组件在 prompt 约束上有什么不同？
4. 考虑 Svelte 的响应式语法 (`$:`) 是否需要在 guidelines 中特别说明？

### 练习 4: 改进错误反馈重试

当前 `_retry_with_error_feedback` 只做一次重试。设计一个改进方案：

1. 阅读 `spec_analyzer.py:256-319` 的现有实现
2. 考虑：如果重试也返回了无效 JSON，但这次的错误不同（例如第一次是缺少逗号，重试后变成了引号未转义），是否值得再试一次？
3. 设计方案需要考虑：
   - 最大重试次数上限（避免无限循环）
   - Token 消耗控制（每次重试都消耗 token）
   - 渐进式截断（如果 3000 字符太长导致问题，缩短到 1500 再试）
4. 权衡：更多重试 vs 直接使用 safe defaults，在什么场景下哪个更合理？

---

## 附录: 提示词工程原则总结

从本项目的实际代码中提炼的 10 条 Prompt Engineering 原则：

| # | 原则 | 项目中的体现 | 源码位置 |
|---|------|-------------|----------|
| 1 | **单一职责** | 每趟只做一件事（发散 or 收敛） | Two-Pass 架构 |
| 2 | **显式否定** | 三重/五重否定约束排除不期望的输出格式 | Pass 1/2 System Prompt |
| 3 | **Constrained Vocabulary** | 19 种 role 枚举 + 使用条件 | spec_analyzer_prompt.py:40-66 |
| 4 | **参数化模板** | Tech Stack、设备信息、同级组件名注入 | codegen_prompt.py:39-41 |
| 5 | **Guided Inference** | 交互推断规则 + "don't fabricate" 约束 | spec_analyzer_prompt.py:106-112 |
| 6 | **渐进恢复** | 五阶段 JSON 解析 + 错误反馈重试 + safe defaults | llm_utils.py:132-191 |
| 7 | **信息隔离** | Strip semantic fields → LLM 只看结构数据 | spec_analyzer.py:36-54 |
| 8 | **Token 节约** | Pass 2 不传截图，超时更短 | spec_analyzer.py:397-407 |
| 9 | **幻觉检测** | pruned vs unmatched children_updates 区分 | spec_merger.py:341-351 |
| 10 | **人机协作** | 机器提供精确值(样式)，LLM 提供语义理解(描述) | spec_merger.py:108-132 |
