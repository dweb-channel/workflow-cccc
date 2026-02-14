"""LLM-based Figma frame classification.

Classifies top-level Figma frames into categories:
- ui_screen: Real UI pages/screens for code generation
- interaction_spec: Interaction annotations/flow descriptions
- design_system: Color palettes, spacing rules, token definitions
- reference: Competitor screenshots, inspiration, old versions
- other: QA checklists, meeting notes, etc.

Two-stage approach:
1. Rule-based pre-filter (zero LLM cost) assigns high/low confidence
2. LLM refines low-confidence items (single call, ~2K tokens)

D6 deliverable for Sprint 3.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# --- Classification categories ---

class FrameCategory(str, Enum):
    UI_SCREEN = "ui_screen"
    INTERACTION_SPEC = "interaction_spec"
    DESIGN_SYSTEM = "design_system"
    REFERENCE = "reference"
    OTHER = "other"


@dataclass
class FrameClassification:
    """Classification result for a single Figma frame."""
    node_id: str
    name: str
    size: str  # e.g., "393×852"
    width: float
    height: float
    bounds: Dict[str, float]
    category: FrameCategory
    confidence: float  # 0.0 - 1.0
    reason: str  # Human-readable reason for classification
    children_count: int = 0
    text_preview: str = ""  # First ~100 chars of text content
    related_to: Optional[str] = None  # For interaction_spec: related UI screen node_id


@dataclass
class ClassificationResult:
    """Full classification result for a Figma page scan."""
    ui_screens: List[FrameClassification] = field(default_factory=list)
    interaction_specs: List[FrameClassification] = field(default_factory=list)
    design_system: List[FrameClassification] = field(default_factory=list)
    reference: List[FrameClassification] = field(default_factory=list)
    other: List[FrameClassification] = field(default_factory=list)

    def all_frames(self) -> List[FrameClassification]:
        return (
            self.ui_screens
            + self.interaction_specs
            + self.design_system
            + self.reference
            + self.other
        )


# --- Constants ---

# Common mobile screen widths (tolerance ±10px)
MOBILE_WIDTHS = {375, 390, 393, 414, 428, 430}  # iPhone variants
ANDROID_WIDTHS = {360, 412}  # Common Android
TABLET_WIDTHS = {744, 768, 810, 820, 834}  # iPad variants
ALL_DEVICE_WIDTHS = MOBILE_WIDTHS | ANDROID_WIDTHS | TABLET_WIDTHS
WIDTH_TOLERANCE = 10
MOBILE_HEIGHT_MIN = 667  # iPhone SE height

# Keywords for rule-based classification
EXCLUDE_KEYWORDS_CN = {"参考", "核查", "标注", "切图", "备注", "旧版", "归档", "废弃", "作废"}
EXCLUDE_KEYWORDS_EN = {"reference", "archive", "old", "deprecated", "unused", "backup", "draft"}
INTERACTION_KEYWORDS_CN = {"交互", "动画", "说明", "流程", "效果说明", "跳转", "状态"}
INTERACTION_KEYWORDS_EN = {"interaction", "animation", "flow", "transition", "spec", "annotation"}
DESIGN_SYSTEM_KEYWORDS_CN = {"取色", "色板", "颜色", "字体", "间距", "规范", "样式"}
DESIGN_SYSTEM_KEYWORDS_EN = {"color", "palette", "typography", "spacing", "tokens", "style guide", "design system"}


# --- LLM Classification Prompt ---

CLASSIFICATION_PROMPT_TEMPLATE = """\
你是一个 Figma 设计稿分析专家。请将以下 Figma 页面中的顶层 frame 分类。

## 分类规则

| 类别 | 说明 | 典型特征 |
|------|------|----------|
| ui_screen | 真实的 UI 页面/屏幕，需要转成代码 | 手机/平板/桌面端标准尺寸；包含 StatusBar、导航栏、内容区等 UI 元素；有实际的文字内容和图片 |
| interaction_spec | 交互说明/动画效果描述 | 包含箭头、连线、流程图；文字标注如"点击跳转"、"展开动画"；通常位于 UI 页面旁边 |
| design_system | 设计系统/取色逻辑/样式规范 | 颜色色块、字体样本、间距标注；名称含"取色"、"规范"、"token"等 |
| reference | 参考图/竞品截图/灵感图 | 大尺寸截图、非标准尺寸；名称含"参考"、"旧版"、"备份" |
| other | 其他（核查单、会议记录、备注等） | 纯文字列表、checklist；不属于以上任何类别 |

## 判断要点

1. **尺寸是关键线索**：宽度 375/390/393/414/360/412 等是手机屏幕，宽度 744-834 是平板
2. **名称和内容**：包含实际 UI 元素名（StatusBar、TabBar、导航等）的更可能是 UI 页面
3. **子节点结构**：UI 页面通常有丰富的嵌套子节点；交互说明通常包含 LINE/ARROW 类型节点
4. **空间位置**：如果一个 frame 紧邻一个 UI 页面（x 坐标差 < 500px），且不是 UI 尺寸，更可能是该页面的交互说明

## 待分类的 frame 列表

{frame_list}

## 输出要求

请返回 JSON 数组，每个元素格式：
```json
{{
  "node_id": "节点ID",
  "category": "ui_screen | interaction_spec | design_system | reference | other",
  "confidence": 0.0-1.0,
  "reason": "一句话说明分类依据",
  "related_to": "如果是 interaction_spec，关联的 UI 页面 node_id（可选）"
}}
```

只返回 JSON 数组，不要其他内容。"""


def _format_frame_for_prompt(frame: Dict[str, Any], index: int) -> str:
    """Format a single frame's metadata for the classification prompt."""
    name = frame.get("name", "Unknown")
    node_id = frame.get("id", frame.get("node_id", ""))
    bbox = frame.get("absoluteBoundingBox", frame.get("bounds", {}))
    w = bbox.get("width", 0)
    h = bbox.get("height", 0)
    x = bbox.get("x", 0)
    y = bbox.get("y", 0)
    node_type = frame.get("type", "FRAME")
    children = frame.get("children", [])
    children_count = len(children)

    # Extract child type summary
    child_types = {}
    for child in children[:15]:
        ct = child.get("type", "UNKNOWN")
        child_types[ct] = child_types.get(ct, 0) + 1

    # Extract first few child names
    child_names = [c.get("name", "") for c in children[:8]]

    # Extract text content preview
    text_preview = frame.get("text_preview", "")
    if not text_preview and children:
        texts = []
        for c in children[:10]:
            if c.get("type") == "TEXT":
                chars = c.get("characters", "")
                if chars:
                    texts.append(chars[:50])
        text_preview = "; ".join(texts)[:100]

    parts = [
        f"{index}. \"{name}\" (node_id={node_id})",
        f"   尺寸: {int(w)}×{int(h)}, 位置: ({int(x)}, {int(y)})",
        f"   类型: {node_type}, 子节点: {children_count} 个",
    ]

    if child_types:
        types_str = ", ".join(f"{k}:{v}" for k, v in sorted(child_types.items()))
        parts.append(f"   子节点类型分布: {types_str}")

    if child_names:
        names_str = ", ".join(n for n in child_names if n)
        if names_str:
            parts.append(f"   子节点名称: {names_str}")

    if text_preview:
        parts.append(f"   文本内容: \"{text_preview}\"")

    return "\n".join(parts)


def build_classification_prompt(frames: List[Dict[str, Any]]) -> str:
    """Build the full LLM classification prompt from frame metadata."""
    frame_entries = []
    for i, frame in enumerate(frames, 1):
        frame_entries.append(_format_frame_for_prompt(frame, i))

    frame_list = "\n\n".join(frame_entries)
    return CLASSIFICATION_PROMPT_TEMPLATE.replace("{frame_list}", frame_list)


# --- Rule-based pre-classification ---

def _matches_device_width(width: float) -> Optional[str]:
    """Check if width matches a known device width. Returns device type or None."""
    for mw in MOBILE_WIDTHS:
        if abs(width - mw) <= WIDTH_TOLERANCE:
            return "mobile"
    for aw in ANDROID_WIDTHS:
        if abs(width - aw) <= WIDTH_TOLERANCE:
            return "android"
    for tw in TABLET_WIDTHS:
        if abs(width - tw) <= WIDTH_TOLERANCE:
            return "tablet"
    return None


def _name_matches_keywords(name: str, keywords: set) -> bool:
    """Check if name contains any of the keywords (case-insensitive)."""
    name_lower = name.lower()
    return any(kw in name_lower for kw in keywords)


def rule_based_classify(frame: Dict[str, Any]) -> FrameClassification:
    """Classify a frame using rule-based heuristics.

    Returns a FrameClassification with confidence:
    - >= 0.8: high confidence, skip LLM
    - < 0.8: low confidence, needs LLM refinement
    """
    name = frame.get("name", "Unknown")
    node_id = frame.get("id", frame.get("node_id", ""))
    bbox = frame.get("absoluteBoundingBox", frame.get("bounds", {}))
    w = bbox.get("width", 0)
    h = bbox.get("height", 0)
    children = frame.get("children", [])
    children_count = len(children)

    size_str = f"{int(w)}×{int(h)}"

    base = dict(
        node_id=node_id,
        name=name,
        size=size_str,
        width=w,
        height=h,
        bounds={"x": bbox.get("x", 0), "y": bbox.get("y", 0), "width": w, "height": h},
        children_count=children_count,
    )

    # --- High confidence rules ---
    # Priority: keyword exclusion > keyword match > device size
    # (a frame named "旧版设计稿" at 393×852 should be REFERENCE, not UI_SCREEN)

    # 1. Name matches exclusion keywords → reference (highest priority)
    if _name_matches_keywords(name, EXCLUDE_KEYWORDS_CN | EXCLUDE_KEYWORDS_EN):
        return FrameClassification(
            **base,
            category=FrameCategory.REFERENCE,
            confidence=0.85,
            reason=f"名称含排除关键词",
        )

    # 2. Name matches interaction keywords
    if _name_matches_keywords(name, INTERACTION_KEYWORDS_CN | INTERACTION_KEYWORDS_EN):
        return FrameClassification(
            **base,
            category=FrameCategory.INTERACTION_SPEC,
            confidence=0.8,
            reason=f"名称含交互说明关键词",
        )

    # 3. Name matches design system keywords
    if _name_matches_keywords(name, DESIGN_SYSTEM_KEYWORDS_CN | DESIGN_SYSTEM_KEYWORDS_EN):
        return FrameClassification(
            **base,
            category=FrameCategory.DESIGN_SYSTEM,
            confidence=0.8,
            reason=f"名称含设计系统关键词",
        )

    # 4. Device-sized frame → likely UI screen
    device_type = _matches_device_width(w)
    if device_type and h >= MOBILE_HEIGHT_MIN:
        return FrameClassification(
            **base,
            category=FrameCategory.UI_SCREEN,
            confidence=0.9,
            reason=f"尺寸匹配{device_type}设备 ({size_str})",
        )

    # --- Low confidence (needs LLM) ---

    # 5. Large frame with many children but non-standard size → ambiguous
    if w > 300 and h > 500 and children_count > 5:
        return FrameClassification(
            **base,
            category=FrameCategory.UI_SCREEN,
            confidence=0.4,
            reason=f"非标准尺寸但结构复杂，需 LLM 确认",
        )

    # 6. Very wide / very short → likely reference or design system
    if w > 1200 or (w > 0 and h / w < 0.3):
        return FrameClassification(
            **base,
            category=FrameCategory.REFERENCE,
            confidence=0.5,
            reason=f"极宽或极扁比例，可能是参考物",
        )

    # 7. Default: low confidence other
    return FrameClassification(
        **base,
        category=FrameCategory.OTHER,
        confidence=0.3,
        reason=f"无法确定分类，需 LLM 判断",
    )


def rule_based_classify_all(
    frames: List[Dict[str, Any]],
    confidence_threshold: float = 0.8,
) -> Tuple[List[FrameClassification], List[Dict[str, Any]]]:
    """Classify all frames with rules. Split into high/low confidence.

    Returns:
        (high_confidence_results, low_confidence_frames_for_llm)
    """
    high_confidence = []
    needs_llm = []

    for frame in frames:
        result = rule_based_classify(frame)
        if result.confidence >= confidence_threshold:
            high_confidence.append(result)
        else:
            needs_llm.append(frame)

    logger.info(
        "Rule-based classification: %d high confidence, %d need LLM",
        len(high_confidence), len(needs_llm),
    )
    return high_confidence, needs_llm


def parse_llm_classification(
    llm_output: str,
    frames: List[Dict[str, Any]],
) -> List[FrameClassification]:
    """Parse LLM classification output JSON into FrameClassification objects.

    Args:
        llm_output: Raw LLM response (should be JSON array)
        frames: Original frame metadata (for size/bounds lookup)

    Returns:
        List of FrameClassification objects
    """
    # Extract JSON from response (handle markdown code blocks)
    json_match = re.search(r"\[[\s\S]*\]", llm_output)
    if not json_match:
        logger.warning("Failed to parse LLM classification output — no JSON array found")
        return []

    try:
        items = json.loads(json_match.group())
    except json.JSONDecodeError as e:
        logger.warning("Failed to parse LLM classification JSON: %s", e)
        return []

    # Build frame lookup
    frame_map = {}
    for f in frames:
        nid = f.get("id", f.get("node_id", ""))
        frame_map[nid] = f

    results = []
    for item in items:
        node_id = item.get("node_id", "")
        category_str = item.get("category", "other")
        confidence = item.get("confidence", 0.7)
        reason = item.get("reason", "LLM 分类")
        related_to = item.get("related_to")

        try:
            category = FrameCategory(category_str)
        except ValueError:
            category = FrameCategory.OTHER

        # Look up frame metadata
        frame = frame_map.get(node_id, {})
        bbox = frame.get("absoluteBoundingBox", frame.get("bounds", {}))
        w = bbox.get("width", 0)
        h = bbox.get("height", 0)

        results.append(FrameClassification(
            node_id=node_id,
            name=frame.get("name", item.get("name", "Unknown")),
            size=f"{int(w)}×{int(h)}",
            width=w,
            height=h,
            bounds={"x": bbox.get("x", 0), "y": bbox.get("y", 0), "width": w, "height": h},
            category=category,
            confidence=confidence,
            reason=f"LLM: {reason}",
            children_count=len(frame.get("children", [])),
            related_to=related_to,
        ))

    return results


def merge_classifications(
    rule_results: List[FrameClassification],
    llm_results: List[FrameClassification],
) -> ClassificationResult:
    """Merge rule-based and LLM classification results into grouped output."""
    all_results = rule_results + llm_results
    result = ClassificationResult()

    for fc in all_results:
        if fc.category == FrameCategory.UI_SCREEN:
            result.ui_screens.append(fc)
        elif fc.category == FrameCategory.INTERACTION_SPEC:
            result.interaction_specs.append(fc)
        elif fc.category == FrameCategory.DESIGN_SYSTEM:
            result.design_system.append(fc)
        elif fc.category == FrameCategory.REFERENCE:
            result.reference.append(fc)
        else:
            result.other.append(fc)

    # Sort UI screens by y-position (top to bottom)
    result.ui_screens.sort(key=lambda f: f.bounds.get("y", 0))

    return result


def associate_interaction_specs(
    classification: ClassificationResult,
    max_distance: float = 500.0,
) -> None:
    """Associate interaction specs with their nearest UI screen by spatial proximity.

    Modifies interaction_specs in-place, setting `related_to` field.
    """
    if not classification.ui_screens or not classification.interaction_specs:
        return

    for spec in classification.interaction_specs:
        if spec.related_to:
            continue  # Already assigned (e.g., by LLM or name matching)

        spec_x = spec.bounds.get("x", 0)
        spec_y = spec.bounds.get("y", 0)
        best_screen = None
        best_distance = float("inf")

        for screen in classification.ui_screens:
            screen_x = screen.bounds.get("x", 0)
            screen_y = screen.bounds.get("y", 0)

            # Euclidean distance between centers
            dx = abs(spec_x - screen_x)
            dy = abs(spec_y - screen_y)
            distance = (dx**2 + dy**2) ** 0.5

            if distance < best_distance:
                best_distance = distance
                best_screen = screen

        if best_screen and best_distance <= max_distance:
            spec.related_to = best_screen.node_id
            logger.debug(
                "Associated spec '%s' → screen '%s' (distance=%.0f)",
                spec.name, best_screen.name, best_distance,
            )


# --- Fallback: pure rule-based classification (no LLM) ---

def classify_frames_rules_only(frames: List[Dict[str, Any]]) -> ClassificationResult:
    """Classify all frames using only rules (fallback when LLM unavailable)."""
    results = [rule_based_classify(f) for f in frames]
    result = merge_classifications(results, [])
    associate_interaction_specs(result)
    return result


# --- Bridge: create LLM classifier callable for FigmaClient.scan_and_classify_frames ---

def create_llm_frame_classifier(
    llm_call: Callable[[str], Awaitable[str]],
) -> Callable[[List[Dict[str, Any]]], Awaitable[List[Dict[str, Any]]]]:
    """Create an LLM classifier callable for FigmaClient.scan_and_classify_frames().

    Bridges D6's prompt builder + parser with D1's llm_classifier slot.

    Args:
        llm_call: Async function that takes a prompt string and returns
                  the LLM's raw text response. The caller is responsible
                  for wiring this to the actual LLM backend (Anthropic SDK,
                  Claude CLI, etc.).

    Returns:
        Async callable matching the scan_and_classify_frames(llm_classifier=...)
        signature: async (frames_summary: List[Dict]) -> List[Dict].
    """

    async def classifier(frames_summary: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        # Adapt D1 summary format → D6 prompt format (Figma-like node dicts)
        adapted_frames = []
        for f in frames_summary:
            bounds = f.get("bounds", {})
            # text_preview may be a list (from _extract_text_content) or a string
            tp = f.get("text_preview", "")
            if isinstance(tp, list):
                tp = "; ".join(str(t) for t in tp[:5])

            adapted = {
                "id": f["node_id"],
                "name": f["name"],
                "type": "FRAME",
                "absoluteBoundingBox": {
                    "x": bounds.get("x", 0),
                    "y": bounds.get("y", 0),
                    "width": bounds.get("width", 0),
                    "height": bounds.get("height", 0),
                },
                "text_preview": tp,
                "children": [{"type": t, "name": ""} for t in f.get("child_types", [])],
            }
            adapted_frames.append(adapted)

        if not adapted_frames:
            return []

        prompt = build_classification_prompt(adapted_frames)
        response = await llm_call(prompt)
        results = parse_llm_classification(response, adapted_frames)

        return [
            {
                "node_id": r.node_id,
                "classification": r.category.value,
                "confidence": r.confidence,
                "reason": r.reason,
            }
            for r in results
        ]

    return classifier
