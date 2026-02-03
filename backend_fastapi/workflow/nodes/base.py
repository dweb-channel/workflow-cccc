"""Built-in Node Type Implementations

This module provides concrete implementations for common workflow node types.
These serve as both production-ready nodes and examples for custom node development.
"""

from __future__ import annotations

import logging
from typing import Any, Dict

from .registry import BaseNodeImpl, register_node_type
from ..engine.safe_eval import SafeEvalError, safe_eval, validate_condition_expression

logger = logging.getLogger(__name__)


@register_node_type(
    node_type="data_source",
    display_name="Data Source",
    description="Provides data from external sources or generates initial workflow data",
    category="data",
    input_schema={
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "source_type": {"type": "string", "enum": ["manual", "api", "database"]},
            "data": {"type": "string", "description": "Static data or template"},
            "output_schema": {"type": "object"},
        },
        "required": ["name"],
    },
    output_schema={
        "type": "object",
        "properties": {
            "data": {"type": "string"},
        },
    },
    icon="database",
    color="#4CAF50",
)
class DataSourceNode(BaseNodeImpl):
    """Node that provides data from external sources or user input.

    For source_type='manual', reads user input from initial_state.request.
    """

    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """Execute data source node.

        Args:
            inputs: Workflow state including initial_state values (e.g., request)

        Returns:
            Dictionary containing the data
        """
        logger.info(f"DataSourceNode {self.node_id}: Executing with inputs keys: {list(inputs.keys())}")

        source_type = self.config.get("source_type", "manual")

        if source_type == "manual":
            # For manual input, read from initial_state.request (passed via workflow run)
            # The frontend sends user input as initial_state.request
            user_input = inputs.get("request", "")
            if not user_input:
                # Fallback to config.data if no runtime input
                user_input = self.config.get("data", "")
            logger.info(f"DataSourceNode {self.node_id}: Manual input = {user_input[:100] if user_input else '(empty)'}...")
            return {"data": user_input}

        # For other source types, generate based on schema (placeholder implementation)
        output_schema = self.config.get("output_schema", {})
        output_data = {}

        for field_name, field_type in output_schema.items():
            if field_type == "string":
                output_data[field_name] = f"sample_{field_name}"
            elif field_type == "number":
                output_data[field_name] = 0
            elif field_type == "timestamp":
                output_data[field_name] = "2026-01-31T00:00:00Z"
            else:
                output_data[field_name] = None

        return output_data if output_data else {"data": ""}


@register_node_type(
    node_type="data_processor",
    display_name="Data Processor",
    description="Processes and transforms data from upstream nodes",
    category="processing",
    input_schema={
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "input_field": {"type": "string"},
            "output_schema": {"type": "object"},
        },
        "required": ["name", "input_field"],
    },
    output_schema={
        "type": "object",
        "properties": {
            "result": {"type": "any"},
        },
    },
    icon="settings",
    color="#2196F3",
)
class DataProcessorNode(BaseNodeImpl):
    """Node that processes data from upstream nodes."""

    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """Execute data processor node.

        Args:
            inputs: Dictionary of inputs from upstream nodes

        Returns:
            Dictionary containing processed result
        """
        logger.info(f"DataProcessorNode {self.node_id}: Executing with inputs: {list(inputs.keys())}")

        input_field = self.config.get("input_field", "")

        # Extract the referenced field value
        # input_field format: "{{node-1.field_name}}"
        input_value = self._resolve_field_reference(input_field, inputs)

        # Simple processing: wrap in result
        result = {
            "result": f"processed_{input_value}",
            "processed_at": "2026-01-31T00:00:00Z",
        }

        return result

    def _resolve_field_reference(self, field_ref: str, inputs: Dict[str, Any]) -> Any:
        """Resolve field reference like '{{node-1.field_name}}'."""
        if not field_ref.startswith("{{") or not field_ref.endswith("}}"):
            return field_ref

        # Extract node_id.field_name
        ref = field_ref[2:-2].strip()
        parts = ref.split(".", 1)

        if len(parts) != 2:
            return None

        node_id, field_name = parts

        # Look up in inputs
        if node_id in inputs and field_name in inputs[node_id]:
            return inputs[node_id][field_name]

        return None


@register_node_type(
    node_type="http_request",
    display_name="HTTP Request",
    description="Makes HTTP requests to external APIs",
    category="integration",
    input_schema={
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "url": {"type": "string", "format": "uri"},
            "method": {"type": "string", "enum": ["GET", "POST", "PUT", "DELETE", "PATCH"]},
            "headers": {"type": "object"},
            "body": {"type": "object"},
        },
        "required": ["name", "url", "method"],
    },
    output_schema={
        "type": "object",
        "properties": {
            "status_code": {"type": "number"},
            "response_body": {"type": "object"},
        },
    },
    icon="globe",
    color="#FF9800",
)
class HttpRequestNode(BaseNodeImpl):
    """Node that makes HTTP requests."""

    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """Execute HTTP request node.

        Args:
            inputs: Dictionary of inputs from upstream nodes

        Returns:
            Dictionary containing HTTP response
        """
        logger.info(f"HttpRequestNode {self.node_id}: Executing")

        url = self.config.get("url", "")
        method = self.config.get("method", "GET")

        # For testing, return mock response
        return {
            "status_code": 200,
            "response_body": {
                "message": f"Mock response for {method} {url}",
            },
        }

    def validate_config(self) -> list[Dict[str, str]]:
        """Validate HTTP request configuration."""
        errors = super().validate_config()

        url = self.config.get("url", "")
        method = self.config.get("method", "")

        # Validate URL format
        if url and not (url.startswith("http://") or url.startswith("https://")):
            errors.append({
                "field": "url",
                "error": "必须是有效的 URL 格式",
            })

        # Validate method
        valid_methods = ["GET", "POST", "PUT", "DELETE", "PATCH"]
        if method and method not in valid_methods:
            errors.append({
                "field": "method",
                "error": f"必须是 {', '.join(valid_methods)} 之一",
            })

        return errors


@register_node_type(
    node_type="condition",
    display_name="Condition",
    description="Routes workflow based on conditional logic",
    category="control",
    input_schema={
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "condition": {"type": "string"},
            "true_branch": {"type": "string"},
            "false_branch": {"type": "string"},
        },
        "required": ["name", "condition"],
    },
    output_schema={
        "type": "object",
        "properties": {
            "branch_taken": {"type": "string"},
            "condition_result": {"type": "boolean"},
        },
    },
    icon="git-branch",
    color="#9C27B0",
)
class ConditionNode(BaseNodeImpl):
    """Node that evaluates conditions for branching.

    The condition expression is evaluated against the current workflow state
    using a safe expression evaluator (no arbitrary code execution).

    Supported expressions:
    - Comparisons: status == "success", count > 0
    - Boolean logic: x > 0 and y < 100
    - Field access: node_1.field_name, data["key"]
    """

    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """Execute condition node.

        Evaluates the condition expression against the current state.
        The result determines which outgoing conditional edge is taken.

        Args:
            inputs: Dictionary of inputs from upstream nodes

        Returns:
            Dictionary containing branch decision and condition result
        """
        logger.info(f"ConditionNode {self.node_id}: Executing")

        condition_expr = self.config.get("condition", "")
        true_branch = self.config.get("true_branch", "")
        false_branch = self.config.get("false_branch", "")

        if not condition_expr:
            logger.warning(f"ConditionNode {self.node_id}: No condition expression, defaulting to true")
            condition_result = True
        else:
            try:
                condition_result = bool(safe_eval(condition_expr, inputs))
                logger.info(
                    f"ConditionNode {self.node_id}: '{condition_expr}' evaluated to {condition_result}"
                )
            except SafeEvalError as e:
                logger.error(
                    f"ConditionNode {self.node_id}: Condition evaluation failed: {e}"
                )
                condition_result = False

        branch_taken = true_branch if condition_result else false_branch

        return {
            "branch_taken": branch_taken,
            "condition_result": condition_result,
        }

    def validate_config(self) -> list[Dict[str, str]]:
        """Validate condition node configuration."""
        errors = super().validate_config()

        condition_expr = self.config.get("condition", "")
        if condition_expr:
            expr_errors = validate_condition_expression(condition_expr)
            for err in expr_errors:
                errors.append({"field": "condition", "error": err})

        return errors


@register_node_type(
    node_type="output",
    display_name="Output",
    description="Outputs workflow results to external destinations",
    category="output",
    input_schema={
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "format": {"type": "string", "enum": ["json", "csv", "xml"]},
            "destination": {"type": "string"},
        },
        "required": ["name", "format"],
    },
    output_schema={
        "type": "object",
        "properties": {
            "success": {"type": "boolean"},
            "output_location": {"type": "string"},
        },
    },
    icon="download",
    color="#607D8B",
)
class OutputNode(BaseNodeImpl):
    """Node that outputs workflow results."""

    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """Execute output node.

        Args:
            inputs: Dictionary of inputs from upstream nodes

        Returns:
            Dictionary containing output status
        """
        logger.info(f"OutputNode {self.node_id}: Executing")

        output_format = self.config.get("format", "json")
        destination = self.config.get("destination", "stdout")

        # For testing, return mock success
        return {
            "success": True,
            "output_location": destination,
            "format": output_format,
        }
