"""Node System: registry, base types, and agent node implementations."""

# Import node modules to auto-register node types
from . import base  # noqa: F401 - registers data_source, data_processor, condition, output, http_request
from . import agents  # noqa: F401 - registers llm_agent, verify
from . import state  # noqa: F401 - registers get_current_item, update_state
from . import design  # noqa: F401 - registers design_analyzer, skeleton_generator, component_generator, visual_diff, assembler
from . import spec_nodes  # noqa: F401 - registers frame_decomposer, spec_assembler

from .registry import (
    NODE_CLASSES,
    NODE_REGISTRY,
    BaseNode,
    BaseNodeImpl,
    NodeDefinition,
    create_node,
    get_node_definition,
    is_node_type_registered,
    list_node_types,
    list_node_types_by_category,
    register_node_type,
)

__all__ = [
    "NODE_CLASSES",
    "NODE_REGISTRY",
    "BaseNode",
    "BaseNodeImpl",
    "NodeDefinition",
    "create_node",
    "get_node_definition",
    "is_node_type_registered",
    "list_node_types",
    "list_node_types_by_category",
    "register_node_type",
]
