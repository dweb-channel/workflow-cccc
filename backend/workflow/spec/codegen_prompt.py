"""Code Generation Prompt Templates

Prompt design for Phase 3 (CodeGenNode): takes a component spec + screenshot
and generates production-ready frontend code.

Tech stack is injected as a variable — defaults to React + Tailwind.
"""

CODEGEN_SYSTEM_PROMPT = """\
You are an expert frontend developer. Your job is to convert a UI component \
specification (with screenshot) into production-ready code.

Your output must be **machine-readable JSON** — no markdown, no explanation, \
no code fences. Return a single JSON object.

## Your Task

You receive:
1. A **screenshot** of one UI component (cropped from a design tool)
2. A **component spec** with structural + semantic data (bounds, layout, \
sizing, style, role, description, interaction)
3. **Page context** (device info, sibling components, page layout)
4. **Tech stack** configuration

You must generate a complete, self-contained component file.

## Output Schema

```
{{
  "component_name": "<PascalCase component name>",
  "file_name": "<component_name>.{file_ext}",
  "code": "<complete component source code>",
  "dependencies": ["<npm packages used>"],
  "tailwind_classes_used": ["<tailwind utility classes used>"]
}}
```

## Tech Stack: {tech_stack}

{tech_stack_guidelines}

## Code Quality Rules

1. **Match the screenshot exactly** — colors, spacing, typography, layout, \
border radius, shadows must match the spec values
2. **Use spec values directly** — don't approximate colors or sizes. Use \
the exact hex values, pixel dimensions, and spacing from the spec
3. **Responsive within component** — the component should work at the \
specified width but not hardcode pixel positions for internal elements
4. **Self-contained** — each component is a single file with no external \
dependencies beyond the tech stack (no custom hooks, no shared utils)
5. **Semantic HTML** — use appropriate HTML elements based on the component \
role (nav, header, footer, button, etc.)
6. **Interaction states** — implement hover/active/disabled states as \
described in the spec's interaction.states array
7. **Click handlers** — add onClick/onPress handlers as described in the \
spec's interaction.behaviors array. Use console.log placeholders for \
navigation actions
8. **Accessibility** — include aria-labels for interactive elements, \
alt text for images
9. **No placeholder images** — for image components, use a colored \
div with the image dimensions as placeholder. Add a comment noting \
the image source should be provided
10. **Icons** — use text/emoji placeholders for icons with a comment \
noting the icon name from the spec (e.g. "arrow-left", "close")
11. **Collapsed children** — the spec may include `children_collapsed: N`. \
This means N child elements exist in the design but were pruned from the spec. \
Look at the screenshot to see what these children are, and implement them as \
internal elements with content matching the screenshot.
"""

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

CODEGEN_TECH_STACK_VUE_TAILWIND = """\
- Framework: Vue 3 (Composition API with <script setup>)
- Styling: Tailwind CSS utility classes
- File extension: .vue (Single File Component)
- Use Tailwind for ALL styling
- For values not in Tailwind's default scale, use arbitrary values
"""

CODEGEN_USER_PROMPT = """\
Generate production-ready code for this UI component.

## Device Context
- Device: {device_type} ({device_width}x{device_height}px)
- Page layout: {page_layout_type}

## Page Context (sibling components)
{sibling_context}

## Component Spec
```json
{component_spec_json}
```

## Instructions
1. Study the screenshot carefully — this is the ground truth for visual appearance.
2. Cross-reference with the component spec for exact values (colors, sizes, spacing).
3. Generate a complete, self-contained component file.
4. Use the component's `name` as the function/component name.
5. Match the layout type from the spec:
   - `flex` → use flexbox with the specified direction, gap, justify, align
   - `absolute` → use absolute positioning relative to a parent container
   - `stack` → use a simple vertical or horizontal stack
6. Apply all style properties from the spec (background, corner_radius, shadow, blur).
7. Implement interaction behaviors and states from the spec.
8. The component should accept no props (self-contained with mock data).

Return a single JSON object following the output schema. No markdown, no explanation."""


# Tech stack configs keyed by name
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


def get_tech_stack_config(stack_name: str = "react-tailwind") -> dict:
    """Get tech stack config by name, with fallback to react-tailwind."""
    return TECH_STACKS.get(stack_name, TECH_STACKS["react-tailwind"])


# Output schema for validation
CODEGEN_OUTPUT_SCHEMA = {
    "type": "object",
    "required": ["component_name", "file_name", "code"],
    "properties": {
        "component_name": {"type": "string"},
        "file_name": {"type": "string"},
        "code": {"type": "string"},
        "dependencies": {
            "type": "array",
            "items": {"type": "string"},
        },
        "tailwind_classes_used": {
            "type": "array",
            "items": {"type": "string"},
        },
    },
}


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
    lines = []
    for i, comp in enumerate(components):
        name = comp.get("name", f"component_{i}")
        role = comp.get("role", "other")
        bounds = comp.get("bounds", {})
        w = bounds.get("width", 0)
        h = bounds.get("height", 0)
        y = bounds.get("y", 0)

        # Layout summary
        layout = comp.get("layout", {})
        layout_type = layout.get("type", "")
        layout_detail = layout_type
        if layout_type == "flex":
            direction = layout.get("direction", "")
            gap = layout.get("gap", 0)
            parts = [f"flex {direction}"]
            if gap:
                parts.append(f"gap:{gap}")
            justify = layout.get("justify", "")
            if justify and justify != "start":
                parts.append(justify)
            layout_detail = " ".join(parts)

        summary = f"{name} ({role}, {layout_detail}, {int(w)}x{int(h)}, y:{int(y)})"

        if i == current_index:
            lines.append(f"  >> {summary}  ← YOU ARE GENERATING THIS")
        elif i < current_index:
            lines.append(f"  Above: {summary}")
        else:
            lines.append(f"  Below: {summary}")

    return "\n".join(lines)
