"""Safe Expression Evaluator for Conditional Branching

Uses Python's ast module to parse and evaluate expressions in a restricted
sandbox. Only allows safe operations: comparisons, boolean logic, literals,
and dict-like field access. No function calls, imports, or arbitrary code.

Supported expressions:
- Comparisons: x > 10, status == "success", count != 0
- Boolean logic: x > 0 and y < 100, not is_error
- Literals: "string", 42, 3.14, True, False, None
- Field access: node_1["field"], result.status (dict dot access)
- Arithmetic: x + 1, count * 2 (basic only)
"""

from __future__ import annotations

import ast
import logging
import operator
from typing import Any, Dict

logger = logging.getLogger(__name__)

# Maximum expression length to prevent abuse
MAX_EXPRESSION_LENGTH = 500

# Safe binary operators
_SAFE_COMPARE_OPS = {
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
    ast.Is: operator.is_,
    ast.IsNot: operator.is_not,
    ast.In: lambda a, b: a in b,
    ast.NotIn: lambda a, b: a not in b,
}

_SAFE_BIN_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
}

_SAFE_UNARY_OPS = {
    ast.Not: operator.not_,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}


class SafeEvalError(Exception):
    """Raised when expression evaluation fails."""
    pass


def safe_eval(expression: str, context: Dict[str, Any]) -> Any:
    """Safely evaluate an expression against a context dictionary.

    Args:
        expression: The expression string to evaluate
        context: Dictionary of variable names to values

    Returns:
        The result of evaluating the expression

    Raises:
        SafeEvalError: If expression is invalid or uses unsupported constructs
    """
    if not expression or not expression.strip():
        raise SafeEvalError("Expression cannot be empty")

    expression = expression.strip()

    if len(expression) > MAX_EXPRESSION_LENGTH:
        raise SafeEvalError(
            f"Expression too long ({len(expression)} chars, max {MAX_EXPRESSION_LENGTH})"
        )

    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as e:
        raise SafeEvalError(f"Invalid expression syntax: {e}") from e

    try:
        return _eval_node(tree.body, context)
    except SafeEvalError:
        raise
    except Exception as e:
        raise SafeEvalError(f"Evaluation error: {e}") from e


def _eval_node(node: ast.AST, context: Dict[str, Any]) -> Any:
    """Recursively evaluate an AST node."""

    # Literal values: 42, "hello", True, None
    if isinstance(node, ast.Constant):
        return node.value

    # Variable names: x, status, result
    if isinstance(node, ast.Name):
        name = node.id
        # Python builtins for boolean/none
        if name == "true" or name == "True":
            return True
        if name == "false" or name == "False":
            return False
        if name == "none" or name == "None":
            return None
        if name in context:
            return context[name]
        raise SafeEvalError(f"Unknown variable: '{name}'")

    # Comparisons: x > 10, a == b, x in [1,2,3]
    if isinstance(node, ast.Compare):
        left = _eval_node(node.left, context)
        for op, comparator in zip(node.ops, node.comparators):
            op_func = _SAFE_COMPARE_OPS.get(type(op))
            if op_func is None:
                raise SafeEvalError(f"Unsupported comparison: {type(op).__name__}")
            right = _eval_node(comparator, context)
            if not op_func(left, right):
                return False
            left = right
        return True

    # Boolean operators: x and y, a or b
    if isinstance(node, ast.BoolOp):
        if isinstance(node.op, ast.And):
            return all(_eval_node(v, context) for v in node.values)
        if isinstance(node.op, ast.Or):
            return any(_eval_node(v, context) for v in node.values)
        raise SafeEvalError(f"Unsupported boolean op: {type(node.op).__name__}")

    # Unary operators: not x, -n
    if isinstance(node, ast.UnaryOp):
        op_func = _SAFE_UNARY_OPS.get(type(node.op))
        if op_func is None:
            raise SafeEvalError(f"Unsupported unary op: {type(node.op).__name__}")
        return op_func(_eval_node(node.operand, context))

    # Binary operators: x + 1, count * 2
    if isinstance(node, ast.BinOp):
        op_func = _SAFE_BIN_OPS.get(type(node.op))
        if op_func is None:
            raise SafeEvalError(f"Unsupported binary op: {type(node.op).__name__}")
        left = _eval_node(node.left, context)
        right = _eval_node(node.right, context)
        return op_func(left, right)

    # Subscript access: data["key"], items[0]
    if isinstance(node, ast.Subscript):
        value = _eval_node(node.value, context)
        key = _eval_node(node.slice, context)
        try:
            return value[key]
        except (KeyError, IndexError, TypeError) as e:
            raise SafeEvalError(f"Subscript access failed: {e}") from e

    # Attribute access: result.status (only on dicts)
    if isinstance(node, ast.Attribute):
        value = _eval_node(node.value, context)
        if isinstance(value, dict):
            if node.attr in value:
                return value[node.attr]
            raise SafeEvalError(
                f"Key '{node.attr}' not found in dict"
            )
        raise SafeEvalError(
            "Attribute access only supported on dict-like objects"
        )

    # List literals: [1, 2, 3]
    if isinstance(node, ast.List):
        return [_eval_node(elt, context) for elt in node.elts]

    # Tuple literals: (1, 2)
    if isinstance(node, ast.Tuple):
        return tuple(_eval_node(elt, context) for elt in node.elts)

    # Dict literals: {"a": 1}
    if isinstance(node, ast.Dict):
        return {
            _eval_node(k, context): _eval_node(v, context)
            for k, v in zip(node.keys, node.values)
        }

    # IfExp: x if condition else y
    if isinstance(node, ast.IfExp):
        if _eval_node(node.test, context):
            return _eval_node(node.body, context)
        return _eval_node(node.orelse, context)

    raise SafeEvalError(f"Unsupported expression type: {type(node).__name__}")


def validate_condition_expression(expression: str) -> list[str]:
    """Validate a condition expression without evaluating it.

    Args:
        expression: The expression string to validate

    Returns:
        List of validation error strings. Empty if valid.
    """
    errors = []

    if not expression or not expression.strip():
        errors.append("Condition expression cannot be empty")
        return errors

    expression = expression.strip()

    if len(expression) > MAX_EXPRESSION_LENGTH:
        errors.append(
            f"Expression too long ({len(expression)} chars, max {MAX_EXPRESSION_LENGTH})"
        )
        return errors

    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as e:
        errors.append(f"Invalid syntax: {e}")
        return errors

    # Walk tree to check for unsafe constructs
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            errors.append("Function calls are not allowed in conditions")
        elif isinstance(node, ast.Lambda):
            errors.append("Lambda expressions are not allowed")
        elif isinstance(node, ast.ListComp | ast.SetComp | ast.DictComp | ast.GeneratorExp):
            errors.append("Comprehensions are not allowed")
        elif isinstance(node, ast.Await):
            errors.append("Await expressions are not allowed")
        elif isinstance(node, ast.Starred):
            errors.append("Star expressions are not allowed")

    return errors
