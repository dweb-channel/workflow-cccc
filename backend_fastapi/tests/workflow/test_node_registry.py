"""Unit tests for Node Registry System

Tests cover:
- Node type registration
- Node instance creation
- Configuration validation
- Registry queries
- Protocol conformance
"""

import pytest

from workflow.nodes.registry import (
    NODE_CLASSES,
    NODE_REGISTRY,
    BaseNodeImpl,
    NodeDefinition,
    create_node,
    get_node_definition,
    is_node_type_registered,
    list_node_types,
    list_node_types_by_category,
    register_node_type,
)

# Import node types to trigger registration
from workflow.nodes.base import (
    ConditionNode,
    DataProcessorNode,
    DataSourceNode,
    HttpRequestNode,
    OutputNode,
)


class TestNodeDefinition:
    """Test NodeDefinition dataclass validation."""

    def test_valid_node_definition(self):
        """Test creating valid node definition."""
        definition = NodeDefinition(
            node_type="test_node",
            display_name="Test Node",
            description="Test description",
            category="test",
            input_schema={"type": "object"},
            output_schema={"type": "object"},
        )

        assert definition.node_type == "test_node"
        assert definition.display_name == "Test Node"
        assert definition.description == "Test description"
        assert definition.category == "test"
        assert definition.input_schema == {"type": "object"}
        assert definition.output_schema == {"type": "object"}

    def test_node_definition_with_optional_fields(self):
        """Test node definition with optional fields."""
        definition = NodeDefinition(
            node_type="test_node",
            display_name="Test Node",
            description="Test description",
            category="test",
            input_schema={"type": "object"},
            output_schema={"type": "object"},
            icon="test-icon",
            color="#FF0000",
        )

        assert definition.icon == "test-icon"
        assert definition.color == "#FF0000"

    def test_node_definition_empty_node_type(self):
        """Test that empty node_type raises ValueError."""
        with pytest.raises(ValueError, match="node_type cannot be empty"):
            NodeDefinition(
                node_type="",
                display_name="Test",
                description="Test",
                category="test",
                input_schema={},
                output_schema={},
            )

    def test_node_definition_empty_display_name(self):
        """Test that empty display_name raises ValueError."""
        with pytest.raises(ValueError, match="display_name cannot be empty"):
            NodeDefinition(
                node_type="test",
                display_name="",
                description="Test",
                category="test",
                input_schema={},
                output_schema={},
            )

    def test_node_definition_invalid_input_schema(self):
        """Test that non-dict input_schema raises ValueError."""
        with pytest.raises(ValueError, match="input_schema must be a dictionary"):
            NodeDefinition(
                node_type="test",
                display_name="Test",
                description="Test",
                category="test",
                input_schema="invalid",  # type: ignore
                output_schema={},
            )


class TestNodeRegistration:
    """Test node type registration functionality."""

    def test_builtin_nodes_registered(self):
        """Test that all built-in node types are registered."""
        expected_types = [
            "data_source",
            "data_processor",
            "http_request",
            "condition",
            "output",
        ]

        for node_type in expected_types:
            assert node_type in NODE_REGISTRY
            assert node_type in NODE_CLASSES

    def test_node_definitions_valid(self):
        """Test that all registered node definitions are valid."""
        for node_type, definition in NODE_REGISTRY.items():
            assert isinstance(definition, NodeDefinition)
            assert definition.node_type == node_type
            assert definition.display_name
            assert definition.description
            assert definition.category
            assert isinstance(definition.input_schema, dict)
            assert isinstance(definition.output_schema, dict)

    def test_register_custom_node_type(self):
        """Test registering a custom node type."""

        @register_node_type(
            node_type="custom_test",
            display_name="Custom Test",
            description="Custom test node",
            category="test",
            input_schema={"type": "object"},
            output_schema={"type": "object"},
        )
        class CustomTestNode(BaseNodeImpl):
            async def execute(self, inputs):
                return {"result": "custom"}

        # Verify registration
        assert "custom_test" in NODE_REGISTRY
        assert "custom_test" in NODE_CLASSES
        assert NODE_CLASSES["custom_test"] == CustomTestNode

        # Verify definition
        definition = NODE_REGISTRY["custom_test"]
        assert definition.node_type == "custom_test"
        assert definition.display_name == "Custom Test"


class TestNodeCreation:
    """Test node instance creation."""

    def test_create_data_source_node(self):
        """Test creating a data source node."""
        node = create_node(
            node_id="node-1",
            node_type="data_source",
            config={
                "name": "Test Source",
                "output_schema": {
                    "user_id": "string",
                    "user_name": "string",
                },
            },
        )

        assert node.node_id == "node-1"
        assert node.node_type == "data_source"
        assert node.config["name"] == "Test Source"

    def test_create_data_processor_node(self):
        """Test creating a data processor node."""
        node = create_node(
            node_id="node-2",
            node_type="data_processor",
            config={
                "name": "Test Processor",
                "input_field": "{{node-1.user_id}}",
            },
        )

        assert node.node_id == "node-2"
        assert node.node_type == "data_processor"

    def test_create_http_request_node(self):
        """Test creating an HTTP request node."""
        node = create_node(
            node_id="node-3",
            node_type="http_request",
            config={
                "name": "API Call",
                "url": "https://api.example.com/data",
                "method": "GET",
            },
        )

        assert node.node_id == "node-3"
        assert node.node_type == "http_request"

    def test_create_condition_node(self):
        """Test creating a condition node."""
        node = create_node(
            node_id="node-4",
            node_type="condition",
            config={
                "name": "Branch Logic",
                "condition": "value > 100",
                "true_branch": "node-5",
                "false_branch": "node-6",
            },
        )

        assert node.node_id == "node-4"
        assert node.node_type == "condition"

    def test_create_output_node(self):
        """Test creating an output node."""
        node = create_node(
            node_id="node-5",
            node_type="output",
            config={
                "name": "Export Results",
                "format": "json",
                "destination": "/tmp/output.json",
            },
        )

        assert node.node_id == "node-5"
        assert node.node_type == "output"

    def test_create_node_unknown_type(self):
        """Test that creating unknown node type raises ValueError."""
        with pytest.raises(ValueError, match="Unknown node type"):
            create_node(
                node_id="node-x",
                node_type="nonexistent_type",
                config={},
            )


class TestNodeExecution:
    """Test node execution functionality."""

    @pytest.mark.asyncio
    async def test_data_source_execution(self):
        """Test data source node execution."""
        node = create_node(
            node_id="node-1",
            node_type="data_source",
            config={
                "name": "Test Source",
                "output_schema": {
                    "user_id": "string",
                    "user_name": "string",
                    "created_at": "timestamp",
                },
            },
        )

        result = await node.execute({})

        assert "user_id" in result
        assert "user_name" in result
        assert "created_at" in result
        assert result["user_id"] == "sample_user_id"

    @pytest.mark.asyncio
    async def test_data_processor_execution(self):
        """Test data processor node execution."""
        node = create_node(
            node_id="node-2",
            node_type="data_processor",
            config={
                "name": "Test Processor",
                "input_field": "{{node-1.user_id}}",
            },
        )

        # Simulate upstream node output
        inputs = {
            "node-1": {
                "user_id": "12345",
                "user_name": "test_user",
            }
        }

        result = await node.execute(inputs)

        assert "result" in result
        assert "12345" in str(result["result"])

    @pytest.mark.asyncio
    async def test_http_request_execution(self):
        """Test HTTP request node execution."""
        node = create_node(
            node_id="node-3",
            node_type="http_request",
            config={
                "name": "API Call",
                "url": "https://api.example.com/data",
                "method": "GET",
            },
        )

        result = await node.execute({})

        assert "status_code" in result
        assert result["status_code"] == 200
        assert "response_body" in result


class TestNodeValidation:
    """Test node configuration validation."""

    def test_validate_valid_config(self):
        """Test validation with valid configuration."""
        node = create_node(
            node_id="node-1",
            node_type="data_source",
            config={
                "name": "Test Source",
            },
        )

        errors = node.validate_config()
        assert len(errors) == 0

    def test_validate_missing_required_field(self):
        """Test validation with missing required field."""
        node = create_node(
            node_id="node-2",
            node_type="data_processor",
            config={
                # Missing 'name' and 'input_field'
            },
        )

        errors = node.validate_config()
        assert len(errors) > 0
        assert any(e["field"] == "name" for e in errors)
        assert any(e["field"] == "input_field" for e in errors)

    def test_validate_invalid_url(self):
        """Test validation with invalid URL format."""
        node = create_node(
            node_id="node-3",
            node_type="http_request",
            config={
                "name": "API Call",
                "url": "not-a-valid-url",
                "method": "GET",
            },
        )

        errors = node.validate_config()
        assert len(errors) > 0
        assert any(e["field"] == "url" for e in errors)
        assert any("URL 格式" in e["error"] for e in errors)

    def test_validate_invalid_method(self):
        """Test validation with invalid HTTP method."""
        node = create_node(
            node_id="node-4",
            node_type="http_request",
            config={
                "name": "API Call",
                "url": "https://api.example.com",
                "method": "INVALID_METHOD",
            },
        )

        errors = node.validate_config()
        assert len(errors) > 0
        assert any(e["field"] == "method" for e in errors)


class TestRegistryQueries:
    """Test registry query functions."""

    def test_get_node_definition(self):
        """Test getting node definition by type."""
        definition = get_node_definition("data_source")

        assert definition is not None
        assert definition.node_type == "data_source"
        assert definition.display_name == "Data Source"

    def test_get_node_definition_nonexistent(self):
        """Test getting nonexistent node definition returns None."""
        definition = get_node_definition("nonexistent")
        assert definition is None

    def test_list_node_types(self):
        """Test listing all node types."""
        node_types = list_node_types()

        assert len(node_types) >= 5  # At least the built-in types
        assert all(isinstance(d, NodeDefinition) for d in node_types)

    def test_list_node_types_by_category(self):
        """Test listing node types by category."""
        data_nodes = list_node_types_by_category("data")
        assert len(data_nodes) >= 1
        assert all(d.category == "data" for d in data_nodes)

        processing_nodes = list_node_types_by_category("processing")
        assert len(processing_nodes) >= 1
        assert all(d.category == "processing" for d in processing_nodes)

    def test_is_node_type_registered(self):
        """Test checking if node type is registered."""
        assert is_node_type_registered("data_source") is True
        assert is_node_type_registered("data_processor") is True
        assert is_node_type_registered("nonexistent") is False


class TestProtocolConformance:
    """Test that nodes conform to BaseNode protocol."""

    def test_node_has_required_attributes(self):
        """Test that created nodes have required attributes."""
        node = create_node(
            node_id="node-1",
            node_type="data_source",
            config={"name": "Test"},
        )

        assert hasattr(node, "node_id")
        assert hasattr(node, "node_type")
        assert hasattr(node, "config")
        assert hasattr(node, "execute")
        assert hasattr(node, "validate_config")

    def test_execute_is_async(self):
        """Test that execute method is async."""
        import inspect

        node = create_node(
            node_id="node-1",
            node_type="data_source",
            config={"name": "Test"},
        )

        assert inspect.iscoroutinefunction(node.execute)

    def test_validate_config_returns_list(self):
        """Test that validate_config returns list of dicts."""
        node = create_node(
            node_id="node-1",
            node_type="data_source",
            config={"name": "Test"},
        )

        errors = node.validate_config()
        assert isinstance(errors, list)
        assert all(isinstance(e, dict) for e in errors)
        assert all("field" in e and "error" in e for e in errors)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
