"""Spec Pipeline Nodes — backward-compatible re-exports.

The spec pipeline has been split into focused modules:
- figma_utils: Color/token mapping + Figma property extraction
- figma_spec_builder: Figma node -> ComponentSpec conversion
- frame_decomposer: Node 1 (FrameDecomposerNode)
- spec_analyzer: Node 2 (SpecAnalyzerNode) + Claude CLI utilities
- spec_assembler: Node 3 (SpecAssemblerNode)

This file re-exports all public symbols for backward compatibility.
"""

# Re-export node classes (used by routes/design.py)
from .frame_decomposer import FrameDecomposerNode  # noqa: F401
from .spec_analyzer import SpecAnalyzerNode  # noqa: F401
from .spec_assembler import SpecAssemblerNode  # noqa: F401

# Re-export utility functions (used by tests and other modules)
from .figma_utils import (  # noqa: F401
    apply_token_reverse_map,
    build_token_reverse_map,
    detect_container_layout,
    detect_render_hint,
    figma_color_to_hex,
    figma_corner_radius,
    figma_effects_to_style,
    figma_fills_to_background,
    figma_sizing,
    figma_strokes_to_border,
    figma_text_to_typography,
    _to_component_name,
)

from .figma_spec_builder import (  # noqa: F401
    figma_node_to_component_spec,
    _normalize_bounds,
    _detect_device_type,
    _should_recurse,
)

from .spec_analyzer import _strip_semantic_fields  # noqa: F401
from .llm_utils import _invoke_claude_cli, _parse_llm_json  # noqa: F401
