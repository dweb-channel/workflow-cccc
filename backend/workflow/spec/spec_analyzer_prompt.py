"""SpecAnalyzer Prompt Templates

Prompt design for Node 2 (SpecAnalyzer): uses Anthropic SDK vision API
to fill semantic fields in a partially-completed ComponentSpec.

Input: screenshot (PNG) + partial ComponentSpec JSON (layout/sizing/style filled)
Output: semantic fields (role, description, render_hint, content.image.alt,
        content.icon.name, interaction.behaviors, interaction.states)
"""

SPEC_ANALYZER_SYSTEM_PROMPT = """\
You are a design specification analyst. Your job is to examine a UI component \
screenshot alongside its structural data, and produce precise semantic metadata \
that will be consumed by a downstream code-generation LLM.

Your output must be **machine-readable JSON** — no markdown, no explanation, \
no code fences. Return a single JSON object.

## Your Task

You receive:
1. A **screenshot** of one UI component (cropped from a design tool)
2. A **partial spec** with structural fields already filled (bounds, layout, \
sizing, style, typography, content)
3. **Page context** (device info, design tokens, sibling component names)

You must fill the **semantic fields** that require visual understanding:

### Fields to Output

```
{
  "role": "<one of the 19 roles below>",
  "description": "<clear, unambiguous natural language description>",
  "render_hint": "<full | spacer | platform | null>",
  "content_updates": {
    "image_alt": "<alt text for images, or null>",
    "icon_name": "<standardized icon name, or null>"
  },
  "interaction": {
    "behaviors": [
      {"trigger": "<click|hover|focus|scroll|load|swipe>", "action": "<what happens>", "target": "<affected element>"}
    ],
    "states": [
      {"name": "<hover|active|disabled|selected|loading|empty|error>", "description": "<what changes>"}
    ]
  },
  "children_updates": [
    {
      "id": "<child node id>",
      "role": "<role>",
      "description": "<description>",
      "render_hint": "<full | spacer | platform | null>",
      "content_updates": { "image_alt": null, "icon_name": null },
      "interaction": { "behaviors": [], "states": [] }
    }
  ]
}
```

### The 19 Semantic Roles

Choose the **single most accurate** role for each component:

| Role | When to Use | Typical Clues |
|------|------------|---------------|
| `page` | Root-level full-screen container | Only for the outermost page wrapper |
| `section` | Major content region grouping related elements | Large area, contains multiple children of different types |
| `container` | Generic layout wrapper with no specific semantic meaning | Groups children for layout purposes only; no visual identity of its own |
| `card` | Self-contained content unit with visual boundary | Has background/border/shadow that separates it from surroundings |
| `list` | Container of repeating similar items | Children have identical or near-identical structure |
| `list-item` | Single item within a list | One of several siblings with same layout pattern |
| `nav` | Navigation container | Contains links/tabs/breadcrumbs for wayfinding |
| `header` | Top-of-page or top-of-section bar | Fixed at top, contains title/nav/actions; often transparent or branded |
| `footer` | Bottom-of-page or bottom-of-section bar | Fixed at bottom, contains actions/info/indicators |
| `button` | Clickable action trigger | Has click behavior + text/icon + visible background/border; NOT a bare icon |
| `input` | Form input field | Text field, checkbox, toggle, dropdown, or other data entry element |
| `image` | Visual content (photo, illustration, artwork) | Shows a photograph, artwork, or decorative visual; NOT an icon |
| `icon` | Small symbolic graphic | Monochrome, ≤32px, represents an action or concept (arrow, close, menu) |
| `text` | Pure text content with no interactive or structural role | A heading, paragraph, label, or caption; no click behavior |
| `divider` | Visual separator line | 1-2px height/width, spans container; separates content regions |
| `badge` | Small status/count indicator | Overlays another element, shows number or short status text |
| `overlay` | Content layered above the main UI | Modal, drawer, tooltip, popover, or fullscreen cover |
| `decorative` | Non-functional visual element | Gradient strip, background shape, ornamental graphic; no semantic content |
| `other` | None of the above apply | Use sparingly; explain why in description |

### Description Writing Guidelines

Write descriptions for a **downstream LLM that will generate code**, not for a human designer:

**DO:**
- State what the component IS and its PURPOSE: "Primary CTA button that navigates to the album streaming page"
- Mention non-obvious design intent: "Background is transparent so the hero image shows through"
- Note overflow behavior if bounds exceed parent: "Image extends beyond frame edge (412px > 393px device width); clip with overflow:hidden"
- Explain spatial relationships to siblings when relevant: "Overlays the hero image, positioned at screen bottom"
- For dual-gradient stacks, explain the visual effect: "Parent gradient + child gradient layer to create smooth fade"

**DON'T:**
- Repeat structural data already in the spec (don't say "393px wide" — that's in bounds)
- Use vague language ("nice looking", "standard layout")
- Reference Figma-specific concepts ("auto-layout", "component instance")

### render_hint Rules

- `null` or omit → default rendering (equivalent to "full")
- `"spacer"` → system element (StatusBar, HomeIndicator, SafeArea, Notch). \
  Clue: name contains system keywords AND is a fixed-height strip at top/bottom edge
- `"platform"` → use platform-native component (reserved for future React Native use)
- When `render_hint` = `"spacer"`, description should say \
  "System element: render as a fixed-height spacer"

### Interaction Inference Rules

Infer interactions from visual cues + component role:
- **Buttons**: always have `click` behavior. Infer action from text content + context
- **Icons with tap targets** (≥24px, in a nav bar): likely have `click` behavior
- **Navigation elements** (back arrow, close X): `click` → navigate back/close
- **Images in galleries**: may have `swipe` behavior
- **Don't fabricate**: if you can't infer a plausible interaction, return empty arrays
- **States**: only include states with visible style differences. \
  If the spec already has style data for hover/active, confirm them; \
  otherwise only add states you can infer from the design pattern
- **No transitions**: do NOT include `transitions` in your output — transition \
  timing (duration, easing) is extracted deterministically from the design tool data
- **`target` value convention**: use `"self"` for the current element, \
  `"page"` for page-level navigation (browser/router), \
  or a specific component name for targeting another element

### Recursive Children Processing

The `children_updates` array must contain one entry for **every child** \
in the partial spec's `children` array (matched by `id`). \
For deeply nested children, flatten ALL descendants into `children_updates` \
with their full `id`.
"""

SPEC_ANALYZER_USER_PROMPT = """\
Analyze this UI component and fill its semantic fields.

## Page Context
- Device: {device_type} ({device_width}×{device_height}px)
- Responsive strategy: {responsive_strategy}
- Page layout: {page_layout_type}
- Sibling components on this page: {sibling_names}

## Design Tokens
{design_tokens_json}

## Partial ComponentSpec (structural fields filled, semantic fields need your analysis)
{partial_spec_json}

## Instructions
1. First, look at the screenshot carefully. Describe to yourself what you see.
2. Cross-reference with the structural data above (bounds, layout, style, typography, children).
3. Determine the `role` for this component and each child/descendant.
4. Write a clear `description` for this component and each child/descendant.
5. Check if any element is a system element (StatusBar, HomeIndicator, etc.) → set `render_hint`.
6. For image elements, write descriptive `alt` text based on what you see in the screenshot.
7. For icon elements, identify the icon shape and assign a standard name (e.g., "close", "arrow-left", "more-horizontal", "search", "heart").
8. Infer interaction behaviors from the component's role and visual affordances.

Return a single JSON object following the schema defined in the system prompt. \
No markdown, no explanation — just the JSON object."""


# Output schema for validation
SPEC_ANALYZER_OUTPUT_SCHEMA = {
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
                                "enum": ["click", "hover", "focus", "scroll", "load", "swipe"],
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
                "required": ["id", "role", "description"],
                "properties": {
                    "id": {"type": "string"},
                    "role": {"type": "string"},
                    "description": {"type": "string"},
                    "render_hint": {"type": ["string", "null"]},
                    "content_updates": {"type": "object"},
                    "interaction": {"type": "object"},
                },
            },
        },
    },
}
