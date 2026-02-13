"""Node Registry System for Dynamic Workflow

This module provides a protocol-based node registration system that allows
dynamic node type registration and instantiation.

Key Components:
- NodeDefinition: Metadata for node types
- BaseNode: Protocol/interface for all nodes
- register_node_type: Decorator for registering node types
- create_node: Factory function for node instantiation

Design Principles:
- Protocol-based design for flexibility
- Type-safe with full typing support
- Extensible for future node types
- Backward compatible with existing hardcoded nodes
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Protocol, Type, TypeVar

logger = logging.getLogger(__name__)

# Type variable for node classes
T = TypeVar("T", bound="BaseNode")


@dataclass
class NodeDefinition:
    """Metadata definition for a node type.

    Attributes:
        node_type: Unique identifier for the node type (e.g., "data_source")
        display_name: Human-readable name for UI display
        description: Brief description of node functionality
        category: Category for grouping (e.g., "data", "processing", "output")
        input_schema: JSON schema for input configuration validation
        output_schema: JSON schema for output structure definition
        icon: Optional icon identifier for UI rendering
        color: Optional color code for UI theming
    """

    node_type: str
    display_name: str
    description: str
    category: str
    input_schema: Dict[str, Any]
    output_schema: Dict[str, Any]
    icon: Optional[str] = None
    color: Optional[str] = None

    def __post_init__(self):
        """Validate node definition after initialization."""
        if not self.node_type:
            raise ValueError("node_type cannot be empty")
        if not self.display_name:
            raise ValueError("display_name cannot be empty")
        if not isinstance(self.input_schema, dict):
            raise ValueError("input_schema must be a dictionary")
        if not isinstance(self.output_schema, dict):
            raise ValueError("output_schema must be a dictionary")


class BaseNode(Protocol):
    """Protocol defining the interface for all workflow nodes.

    All node implementations must conform to this protocol to be compatible
    with the dynamic workflow system.

    Attributes:
        node_id: Unique identifier for this node instance
        node_type: Type identifier matching NodeDefinition
        config: Configuration dictionary for this node instance
    """

    node_id: str
    node_type: str
    config: Dict[str, Any]

    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """Execute the node's logic.

        Args:
            inputs: Dictionary of input values from upstream nodes

        Returns:
            Dictionary of output values for downstream nodes

        Raises:
            ValueError: If inputs don't match expected schema
            RuntimeError: If execution fails
        """
        ...

    def validate_config(self) -> List[Dict[str, str]]:
        """Validate node configuration against schema.

        Returns:
            List of validation errors, each containing:
                - field: Name of the invalid field
                - error: Description of the validation error
            Empty list if validation passes
        """
        ...


class BaseNodeImpl(ABC):
    """Abstract base class providing common node functionality.

    This class provides a concrete implementation of common node operations
    while leaving the execute logic to be implemented by subclasses.
    """

    def __init__(self, node_id: str, node_type: str, config: Dict[str, Any]):
        """Initialize base node.

        Args:
            node_id: Unique identifier for this node instance
            node_type: Type identifier matching NodeDefinition
            config: Configuration dictionary for this node instance
        """
        self.node_id = node_id
        self.node_type = node_type
        self.config = config

    @abstractmethod
    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """Execute the node's logic. Must be implemented by subclasses."""
        pass

    def validate_config(self) -> List[Dict[str, str]]:
        """Default validation implementation.

        Subclasses can override this to provide specific validation logic.
        """
        errors = []

        # Get node definition for schema validation
        definition = NODE_REGISTRY.get(self.node_type)
        if not definition:
            errors.append({
                "field": "node_type",
                "error": f"Unknown node type: {self.node_type}"
            })
            return errors

        # Basic schema validation (can be extended)
        required_fields = definition.input_schema.get("required", [])
        for field_name in required_fields:
            if field_name not in self.config:
                errors.append({
                    "field": field_name,
                    "error": f"Required field '{field_name}' is missing"
                })

        return errors


# Global registry for node types
NODE_REGISTRY: Dict[str, NodeDefinition] = {}
NODE_CLASSES: Dict[str, Type[BaseNode]] = {}


def register_node_type(
    node_type: str,
    display_name: str,
    description: str,
    category: str,
    input_schema: Dict[str, Any],
    output_schema: Dict[str, Any],
    icon: Optional[str] = None,
    color: Optional[str] = None,
) -> Callable[[Type[T]], Type[T]]:
    """Decorator to register a node type.

    This decorator registers both the node definition metadata and the
    node class implementation.

    Args:
        node_type: Unique identifier for the node type
        display_name: Human-readable name
        description: Brief description
        category: Category for grouping
        input_schema: JSON schema for input validation
        output_schema: JSON schema for output structure
        icon: Optional icon identifier
        color: Optional color code

    Returns:
        Decorator function that registers the class

    Example:
        @register_node_type(
            node_type="data_source",
            display_name="Data Source",
            description="Provides data from external sources",
            category="data",
            input_schema={"type": "object", "properties": {...}},
            output_schema={"type": "object", "properties": {...}}
        )
        class DataSourceNode(BaseNodeImpl):
            async def execute(self, inputs):
                return {"data": "..."}
    """

    def decorator(cls: Type[T]) -> Type[T]:
        # Create node definition
        definition = NodeDefinition(
            node_type=node_type,
            display_name=display_name,
            description=description,
            category=category,
            input_schema=input_schema,
            output_schema=output_schema,
            icon=icon,
            color=color,
        )

        # Register definition and class
        NODE_REGISTRY[node_type] = definition
        NODE_CLASSES[node_type] = cls

        logger.info(f"Registered node type: {node_type} ({display_name})")

        return cls

    return decorator


def create_node(
    node_id: str,
    node_type: str,
    config: Dict[str, Any],
) -> BaseNode:
    """Factory function to create a node instance.

    Args:
        node_id: Unique identifier for this node instance
        node_type: Type identifier (must be registered)
        config: Configuration dictionary for this node instance

    Returns:
        Instantiated node object conforming to BaseNode protocol

    Raises:
        ValueError: If node_type is not registered

    Example:
        node = create_node(
            node_id="node-1",
            node_type="data_source",
            config={"url": "https://api.example.com/data"}
        )
        result = await node.execute({})
    """
    if node_type not in NODE_CLASSES:
        available_types = list(NODE_CLASSES.keys())
        raise ValueError(
            f"Unknown node type: {node_type}. "
            f"Available types: {available_types}"
        )

    node_class = NODE_CLASSES[node_type]
    node = node_class(node_id=node_id, node_type=node_type, config=config)

    logger.debug(f"Created node: {node_id} (type={node_type})")

    return node


def get_node_definition(node_type: str) -> Optional[NodeDefinition]:
    """Get the definition for a registered node type.

    Args:
        node_type: Type identifier

    Returns:
        NodeDefinition if found, None otherwise
    """
    return NODE_REGISTRY.get(node_type)


def list_node_types() -> List[NodeDefinition]:
    """List all registered node types.

    Returns:
        List of all registered NodeDefinition objects
    """
    return list(NODE_REGISTRY.values())


def list_node_types_by_category(category: str) -> List[NodeDefinition]:
    """List all registered node types in a specific category.

    Args:
        category: Category filter

    Returns:
        List of NodeDefinition objects matching the category
    """
    return [
        definition
        for definition in NODE_REGISTRY.values()
        if definition.category == category
    ]


def is_node_type_registered(node_type: str) -> bool:
    """Check if a node type is registered.

    Args:
        node_type: Type identifier to check

    Returns:
        True if registered, False otherwise
    """
    return node_type in NODE_REGISTRY
