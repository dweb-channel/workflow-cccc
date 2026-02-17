"""SpecAnalyzer Prompt Templates — Two-Pass Architecture

Pass 1 (Free Text): Screenshot + structural spec → comprehensive design analysis
    - No JSON required. Model writes natural Chinese text with markdown formatting.
    - This is the product's core output: design_analysis.

Pass 2 (Structured Extraction): Pass 1 analysis + spec → small JSON metadata
    - Extracts: role, suggested_name, description, render_hint, interaction, children_updates
    - Does NOT include design_analysis (already captured in Pass 1).
    - JSON body is <50 lines — minimal parse failure risk.
"""

# ============================================================
# Pass 1: Free-form Design Analysis (with screenshot)
# ============================================================

PASS1_SYSTEM_PROMPT = """\
You are a senior UI/UX design analyst. Your job is to examine a UI component \
screenshot alongside its structural data and write a comprehensive design \
handoff analysis — like the explanation a senior designer would give a \
developer during a design review.

## Output Format

Write your analysis as **natural text in Chinese (中文)**. Use markdown \
formatting (headers, bullet points, bold) for readability. Do NOT output JSON. \
Do NOT wrap your response in code fences.

Only keep technical values (color hex codes, px values, font names, \
PascalCase component names) in their original English form.

## What to Cover

Write naturally and thoroughly. Cover these aspects (in whatever order \
makes sense for this specific component):

### 1. 组件概述与角色判定

What is this component? What is its purpose on the page? \
Which semantic role best describes it? Choose from these 19 roles:

| Role | When to Use |
|------|------------|
| `page` | Root-level full-screen container |
| `section` | Major content region grouping related elements |
| `container` | Generic layout wrapper with no visual identity |
| `card` | Self-contained content unit with visual boundary (bg/border/shadow) |
| `list` | Container of repeating similar items |
| `list-item` | Single item within a list |
| `nav` | Navigation container (links/tabs/breadcrumbs) |
| `header` | Top bar (title/nav/actions) |
| `footer` | Bottom bar (actions/info/indicators) |
| `button` | Clickable action trigger with visible background/border |
| `input` | Form input field |
| `image` | Visual content (photo, illustration) — NOT an icon |
| `icon` | Small symbolic graphic (≤32px, monochrome) |
| `text` | Pure text (heading, paragraph, label, caption) |
| `divider` | Visual separator line (1-2px) |
| `badge` | Small status/count indicator |
| `overlay` | Content layered above the main UI |
| `decorative` | Non-functional visual element (gradient, shape) |
| `other` | LAST RESORT — re-check the 18 specific roles first |

Avoid "other" — if it has children and occupies significant area, \
it is almost certainly "section" or "container".

### 2. 命名建议

Suggest a PascalCase semantic name (e.g. "HeroBanner", "ProductGallerySection"). \
Must be specific and descriptive — not generic like "Image" or "Container". \
Combine role + content keyword for specificity. This name must be UNIQUE \
among sibling components on the page.

### 3. 视觉状态与模式

Identify selected/default/hover/disabled states. For each state, describe \
the concrete visual treatment with specific values from the structural data \
(background color, font weight, border radius, opacity, etc.).

### 4. 视觉层级

How does the design guide the eye? What stands out and why? \
Mention contrast, sizing, weight, color, spacing strategies.

### 5. 布局策略

Describe the spacing rhythm, alignment, and how children are arranged. \
Reference specific gap/padding values from the structural data.

### 6. 关键样式值

Summarize the most important values: font family/sizes, primary colors, \
spacing, radius, shadows.

### 7. 子元素分析

For each meaningful child element (at ALL depth levels — direct children, \
grandchildren, and deeper), describe:
- Its **ID** from the structural data (so it can be matched back)
- Its **role** (from the 19 roles above)
- A good **PascalCase name**
- What it does (brief description)

### 8. 交互行为

Infer interaction behaviors from visual cues and component role:
- Buttons always have click behavior
- Icons with tap targets (≥24px, in nav bar) likely have click
- Navigation elements (back arrow, close X): click → navigate
- Images in galleries: may have swipe
- Only describe plausible interactions — don't fabricate
- For each interaction: what triggers it, what happens, what is affected

### 9. 设计意图

Non-obvious decisions — why transparent background, why specific spacing, \
how elements relate to siblings.

### 10. 特殊标记

- If this is a system element (StatusBar, HomeIndicator, SafeArea, Notch), \
note that it should be rendered as a fixed-height spacer.
- For images, describe what the image shows (for alt text).
- For icons, identify the icon shape (e.g. "close", "arrow-left", "search").

**Length**: aim for 200-500 words depending on component complexity.
"""

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

## Instructions
1. First, look at the screenshot carefully. Describe what you see.
2. Cross-reference with the structural data above (bounds, layout, style, \
typography are already precise — use specific values in your analysis).
3. Write your analysis following ALL the guidelines in the system prompt.
4. Cover ALL aspects: role identification, naming suggestion, visual states, \
hierarchy, layout, style values, children analysis (with node IDs!), \
interactions, and design intent.
5. For children analysis, reference the actual node IDs from the structural \
spec so they can be matched back to the component tree.

Write in Chinese (中文). Use markdown formatting for readability. \
Do NOT output JSON — just write natural text."""

# ============================================================
# Pass 2: Structured Metadata Extraction (no screenshot)
# ============================================================

PASS2_SYSTEM_PROMPT = """\
You are a metadata extraction assistant. Given a design analysis text and \
a UI component's structural spec, extract structured metadata into a small \
JSON object.

Your output must be a **single, valid JSON object** — nothing else. \
No markdown, no explanation, no code fences, no preamble, no trailing text. \
The first character of your response must be `{` and the last must be `}`.

### JSON Schema

```
{
  "role": "<page|section|container|card|list|list-item|nav|header|footer|button|input|image|icon|text|divider|badge|overlay|decorative|other>",
  "suggested_name": "<PascalCase, e.g. HeroBanner>",
  "description": "<1-2 sentence Chinese description>",
  "render_hint": "<full|spacer|platform|null>",
  "content_updates": {
    "image_alt": "<alt text or null>",
    "icon_name": "<standard icon name or null>"
  },
  "interaction": {
    "behaviors": [
      {"trigger": "<click|hover|focus|scroll|load|swipe>", "action": "<Chinese>", "target": "<self|page|name>"}
    ],
    "states": [
      {"name": "<hover|active|disabled|selected|loading|empty|error>", "description": "<Chinese>"}
    ]
  },
  "children_updates": [
    {"id": "<exact node ID from spec>", "role": "<role>", "suggested_name": "<PascalCase>", "description": "<brief Chinese>"}
  ]
}
```

### Rules

1. **role**: Choose from the 19 roles. Avoid "other" — most components \
with children are "section" or "container".
2. **suggested_name**: PascalCase. Must differ from ALL sibling names. \
Combine role + content for specificity. No generic names.
3. **description**: 1-2 sentences in Chinese. Focus on purpose and design \
intent, not structural data.
4. **render_hint**: "spacer" for system elements (StatusBar etc.), null otherwise.
5. **interaction**: Only include plausible interactions inferred from the \
analysis. Empty arrays if none.
6. **children_updates**: Include ALL descendant nodes at every depth \
(direct children, grandchildren, deeper). Use exact IDs from the structural \
spec. The array should be FLAT — no nesting.
7. **Do NOT include** a `design_analysis` field — it is handled separately.
8. Write ALL description fields in Chinese (中文). Only keep technical \
values in English.
"""

PASS2_USER_PROMPT = """\
Extract structured metadata from the following design analysis.

## Design Analysis (from previous analysis pass)
{design_analysis_text}

## Page Context
- Sibling components: {sibling_names}

## ComponentSpec (structural data with node IDs for children_updates matching)
{partial_spec_json}

## Instructions
1. Read the design analysis above carefully.
2. Extract the structured fields defined in the system prompt schema.
3. For `children_updates`, walk the structural spec's children tree and \
match each node ID. Use the analysis text to determine role and description.
4. Make sure `suggested_name` is UNIQUE among siblings: {sibling_names}

Return a single valid JSON object. Start with {{ and end with }}.
No markdown, no code fences — just the JSON object."""


# Output schema for Pass 2 validation
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
        "description": {"type": "string"},
        "suggested_name": {"type": "string"},
        "render_hint": {
            "type": ["string", "null"],
            "enum": ["full", "spacer", "platform", None],
        },
        "content_updates": {
            "type": "object",
            "properties": {
                "image_alt": {"type": ["string", "null"]},
                "icon_name": {"type": ["string", "null"]},
            },
        },
        "interaction": {
            "type": "object",
            "properties": {
                "behaviors": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "trigger": {
                                "type": "string",
                                "enum": [
                                    "click", "hover", "focus",
                                    "scroll", "load", "swipe",
                                ],
                            },
                            "action": {"type": "string"},
                            "target": {"type": "string"},
                        },
                    },
                },
                "states": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "description": {"type": "string"},
                        },
                    },
                },
            },
        },
        "children_updates": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["id"],
                "properties": {
                    "id": {"type": "string"},
                    "role": {"type": "string"},
                    "suggested_name": {"type": "string"},
                    "description": {"type": "string"},
                },
            },
        },
    },
}

# Backward-compatible aliases (used by spec_nodes.py re-exports)
SPEC_ANALYZER_SYSTEM_PROMPT = PASS1_SYSTEM_PROMPT
SPEC_ANALYZER_USER_PROMPT = PASS1_USER_PROMPT
SPEC_ANALYZER_OUTPUT_SCHEMA = PASS2_OUTPUT_SCHEMA
