"""State Management Node Types for Batch Workflows

This module provides node types for managing workflow state in loop-based workflows.
These nodes enable dynamic array access and state updates during iteration.

Key Components:
- GetCurrentItemNode: Extracts current item from array by index
- UpdateStateNode: Updates multiple state fields with expressions
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional

from .registry import BaseNodeImpl, register_node_type

logger = logging.getLogger(__name__)


def _safe_get_nested(obj: Any, path: str) -> Any:
    """Safely get a nested value from an object using dot notation.

    Args:
        obj: The object to traverse
        path: Dot-separated path (e.g., "config.max_retries")

    Returns:
        The value at the path, or None if not found
    """
    parts = path.split(".")
    current = obj
    for part in parts:
        if isinstance(current, dict):
            current = current.get(part)
        elif hasattr(current, part):
            current = getattr(current, part)
        else:
            return None
        if current is None:
            return None
    return current


@register_node_type(
    node_type="get_current_item",
    display_name="Get Current Item",
    description="Extracts the current item from an array using an index variable",
    category="state",
    input_schema={
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Node display name"},
            "array_field": {
                "type": "string",
                "description": "State field containing the array (e.g., 'bugs')",
            },
            "index_field": {
                "type": "string",
                "description": "State field containing the current index (e.g., 'current_index')",
            },
            "output_key": {
                "type": "string",
                "description": "Key for the extracted item in output (default: 'current_item')",
            },
        },
        "required": ["name", "array_field", "index_field"],
    },
    output_schema={
        "type": "object",
        "properties": {
            "current_item": {"type": "any", "description": "The item at the current index"},
            "index": {"type": "integer", "description": "The current index value"},
            "has_more": {"type": "boolean", "description": "Whether more items remain"},
        },
    },
    icon="list",
    color="#00BCD4",
)
class GetCurrentItemNode(BaseNodeImpl):
    """Node that extracts the current item from an array by index.

    This node is essential for loop-based workflows where you need to
    process array elements one at a time.

    Example config:
        {
            "name": "Get Current Bug",
            "array_field": "bugs",
            "index_field": "current_index",
            "output_key": "current_bug"
        }

    Given state: {"bugs": ["url1", "url2", "url3"], "current_index": 1}
    Output: {"current_bug": "url2", "index": 1, "has_more": True}
    """

    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        logger.info(f"GetCurrentItemNode {self.node_id}: Executing")

        array_field = self.config.get("array_field", "items")
        index_field = self.config.get("index_field", "current_index")
        output_key = self.config.get("output_key", "current_item")

        # Get array from state
        array = inputs.get(array_field)
        if array is None:
            # Try nested lookup
            array = _safe_get_nested(inputs, array_field)

        if not isinstance(array, list):
            logger.error(f"GetCurrentItemNode {self.node_id}: '{array_field}' is not an array: {type(array)}")
            return {
                output_key: None,
                "index": -1,
                "has_more": False,
                "error": f"Field '{array_field}' is not an array",
            }

        # Get index from state
        index = inputs.get(index_field)
        if index is None:
            index = _safe_get_nested(inputs, index_field)

        if not isinstance(index, int):
            try:
                index = int(index) if index is not None else 0
            except (ValueError, TypeError):
                logger.warning(f"GetCurrentItemNode {self.node_id}: Invalid index, defaulting to 0")
                index = 0

        # Bounds check
        if index < 0 or index >= len(array):
            logger.warning(
                f"GetCurrentItemNode {self.node_id}: Index {index} out of bounds (array length: {len(array)})"
            )
            return {
                output_key: None,
                "index": index,
                "has_more": False,
                "error": f"Index {index} out of bounds",
            }

        current_item = array[index]
        has_more = index < len(array) - 1

        logger.info(
            f"GetCurrentItemNode {self.node_id}: Retrieved item at index {index}, has_more={has_more}"
        )

        return {
            output_key: current_item,
            "index": index,
            "has_more": has_more,
        }

    def validate_config(self) -> List[Dict[str, str]]:
        errors = super().validate_config()

        if not self.config.get("array_field", "").strip():
            errors.append({"field": "array_field", "error": "Array field name is required"})

        if not self.config.get("index_field", "").strip():
            errors.append({"field": "index_field", "error": "Index field name is required"})

        return errors


@register_node_type(
    node_type="update_state",
    display_name="Update State",
    description="Updates workflow state fields with new values or expressions",
    category="state",
    input_schema={
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Node display name"},
            "updates": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "field": {"type": "string", "description": "State field to update"},
                        "value": {"type": "any", "description": "Static value to set"},
                        "expression": {
                            "type": "string",
                            "description": "Expression to evaluate (e.g., 'current_index + 1')",
                        },
                        "append": {
                            "type": "object",
                            "description": "Object to append to an array field",
                        },
                    },
                    "required": ["field"],
                },
                "description": "List of state updates to apply",
            },
        },
        "required": ["name", "updates"],
    },
    output_schema={
        "type": "object",
        "properties": {
            "updated_fields": {
                "type": "array",
                "items": {"type": "string"},
                "description": "List of fields that were updated",
            },
        },
    },
    icon="edit",
    color="#FF9800",
)
class UpdateStateNode(BaseNodeImpl):
    """Node that updates workflow state fields.

    Supports three update modes:
    1. Static value: Set field to a specific value
    2. Expression: Evaluate simple arithmetic/logic expression
    3. Append: Append an object to an array field

    Example config:
        {
            "name": "Update State After Fix",
            "updates": [
                {"field": "current_index", "expression": "current_index + 1"},
                {"field": "retry_count", "value": 0},
                {"field": "results", "append": {"url": "{current_bug}", "status": "completed"}}
            ]
        }

    Note: Expressions support basic arithmetic (+, -, *) and field references.
    Template strings like "{current_bug}" are replaced with actual values.
    """

    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        logger.info(f"UpdateStateNode {self.node_id}: Executing")

        updates = self.config.get("updates", [])
        updated_fields = []
        result = {}

        for update in updates:
            field = update.get("field")
            if not field:
                continue

            try:
                new_value = self._compute_update(update, inputs)
                result[field] = new_value
                updated_fields.append(field)
                logger.info(f"UpdateStateNode {self.node_id}: Updated '{field}' = {new_value}")
            except Exception as e:
                logger.error(f"UpdateStateNode {self.node_id}: Failed to update '{field}': {e}")
                result[f"{field}_error"] = str(e)

        result["updated_fields"] = updated_fields
        return result

    def _compute_update(self, update: Dict[str, Any], inputs: Dict[str, Any]) -> Any:
        """Compute the new value for a state update.

        Args:
            update: Update specification with field, value/expression/append
            inputs: Current workflow state

        Returns:
            The computed new value
        """
        field = update.get("field")

        # Mode 1: Static value
        if "value" in update:
            value = update["value"]
            # Handle template strings in static values
            if isinstance(value, str):
                value = self._render_template(value, inputs)
            return value

        # Mode 2: Expression evaluation
        if "expression" in update:
            return self._evaluate_expression(update["expression"], inputs)

        # Mode 3: Append to array (with optional update_key for nested dict)
        if "append" in update:
            append_obj = update["append"]
            # Render any template strings in the append object
            rendered_obj = self._render_object(append_obj, inputs)

            update_key = update.get("update_key")
            if update_key:
                # Append to a sub-array inside a dict field
                # e.g., field="component_registry", update_key="components"
                parent_dict = inputs.get(field, {})
                if not isinstance(parent_dict, dict):
                    parent_dict = {}
                sub_array = parent_dict.get(update_key, [])
                if not isinstance(sub_array, list):
                    sub_array = []
                updated_dict = {**parent_dict, update_key: sub_array + [rendered_obj]}
                return updated_dict

            # Get current array
            current_array = inputs.get(field, [])
            if not isinstance(current_array, list):
                current_array = []

            # Return the new array with appended item
            return current_array + [rendered_obj]

        # No operation specified, return current value
        return inputs.get(field)

    def _render_template(self, template: str, context: Dict[str, Any]) -> str:
        """Render a template string with {placeholder} substitution.

        Args:
            template: Template string with {field} placeholders
            context: Context dictionary for value lookup

        Returns:
            Rendered string
        """
        def replacer(match: re.Match) -> str:
            key = match.group(1)
            # Direct lookup
            if key in context:
                val = context[key]
                return str(val) if not isinstance(val, str) else val
            # Nested lookup
            val = _safe_get_nested(context, key)
            if val is not None:
                return str(val) if not isinstance(val, str) else val
            return match.group(0)  # Leave unresolved

        return re.sub(r"\{(\w+(?:\.\w+)*)\}", replacer, template)

    def _render_object(self, obj: Any, context: Dict[str, Any]) -> Any:
        """Recursively render template strings in an object.

        Args:
            obj: Object (dict, list, or primitive) to render
            context: Context dictionary for value lookup

        Returns:
            Rendered object with all template strings replaced
        """
        if isinstance(obj, str):
            return self._render_template(obj, context)
        elif isinstance(obj, dict):
            return {k: self._render_object(v, context) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [self._render_object(item, context) for item in obj]
        else:
            return obj

    def _evaluate_expression(self, expr: str, context: Dict[str, Any]) -> Any:
        """Evaluate a simple arithmetic expression.

        Supports:
        - Field references: current_index, retry_count
        - Arithmetic: +, -, *
        - Comparison: <, >, ==, !=, <=, >=

        Args:
            expr: Expression string (e.g., "current_index + 1")
            context: Context dictionary for variable lookup

        Returns:
            Evaluated result
        """
        # Replace field references with values
        tokens = re.split(r"(\s+|\+|\-|\*|<|>|==|!=|<=|>=)", expr)
        evaluated_tokens = []

        for token in tokens:
            token = token.strip()
            if not token:
                continue

            # Check if it's a number
            if re.match(r"^-?\d+(\.\d+)?$", token):
                evaluated_tokens.append(token)
            # Check if it's an operator
            elif token in ["+", "-", "*", "<", ">", "==", "!=", "<=", ">="]:
                evaluated_tokens.append(token)
            # Check if it's a boolean
            elif token.lower() in ["true", "false"]:
                evaluated_tokens.append(token.capitalize())
            # Otherwise it's a field reference
            else:
                value = context.get(token)
                if value is None:
                    value = _safe_get_nested(context, token)
                if value is None:
                    logger.warning(f"UpdateStateNode: Unknown field '{token}' in expression, using 0")
                    value = 0
                evaluated_tokens.append(str(value))

        # Join and evaluate
        eval_expr = " ".join(evaluated_tokens)
        logger.debug(f"UpdateStateNode: Evaluating '{eval_expr}' (from '{expr}')")

        try:
            # Use eval with restricted builtins for safety
            result = eval(eval_expr, {"__builtins__": {}}, {})
            return result
        except Exception as e:
            logger.error(f"UpdateStateNode: Expression evaluation failed: {e}")
            raise ValueError(f"Invalid expression '{expr}': {e}")

    def validate_config(self) -> List[Dict[str, str]]:
        errors = super().validate_config()

        updates = self.config.get("updates", [])
        if not updates:
            errors.append({"field": "updates", "error": "At least one update is required"})
            return errors

        for i, update in enumerate(updates):
            if not update.get("field"):
                errors.append({"field": f"updates[{i}].field", "error": "Field name is required"})

            # Check that at least one operation is specified
            has_operation = any(k in update for k in ["value", "expression", "append"])
            if not has_operation:
                errors.append({
                    "field": f"updates[{i}]",
                    "error": "Must specify 'value', 'expression', or 'append'",
                })

        return errors
