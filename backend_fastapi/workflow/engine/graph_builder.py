"""Dynamic Graph Builder for Workflow Execution

This module provides dynamic workflow graph construction from configuration.
It enables users to define workflows declaratively and execute them using LangGraph.

Key Components:
- WorkflowDefinition: Declarative workflow configuration
- EdgeDefinition: Edge connection definition
- build_graph_from_config: Dynamic graph builder
- Workflow validation and topological sorting

Design Principles:
- Configuration-driven workflow construction
- Validation before execution
- Support for complex DAG structures
- Integration with node registry system
"""

from __future__ import annotations

import logging
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

# Optional langgraph import (only needed for build_graph_from_config)
try:
    from langgraph.graph import END, StateGraph
    LANGGRAPH_AVAILABLE = True
except ImportError:
    LANGGRAPH_AVAILABLE = False
    END = "__end__"  # Placeholder
    StateGraph = None  # Placeholder

from ..nodes.registry import create_node, is_node_type_registered
from .safe_eval import SafeEvalError, safe_eval, validate_condition_expression

logger = logging.getLogger(__name__)


@dataclass
class NodeConfig:
    """Configuration for a single workflow node.

    Attributes:
        id: Unique node identifier
        type: Node type (must be registered in node registry)
        config: Node-specific configuration dictionary
    """

    id: str
    type: str
    config: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        """Validate node configuration."""
        if not self.id:
            raise ValueError("node id cannot be empty")
        if not self.type:
            raise ValueError("node type cannot be empty")


@dataclass
class EdgeDefinition:
    """Definition of an edge connecting two nodes.

    Attributes:
        id: Unique edge identifier
        source: Source node ID
        target: Target node ID
        condition: Optional condition for conditional edges
    """

    id: str
    source: str
    target: str
    condition: Optional[str] = None

    def __post_init__(self):
        """Validate edge definition."""
        if not self.id:
            raise ValueError("edge id cannot be empty")
        if not self.source:
            raise ValueError("source node cannot be empty")
        if not self.target:
            raise ValueError("target node cannot be empty")
        if self.source == self.target:
            raise ValueError(f"self-loop detected: {self.source} -> {self.target}")


@dataclass
class WorkflowDefinition:
    """Declarative workflow definition.

    Attributes:
        name: Workflow name
        nodes: List of node configurations
        edges: List of edge definitions
        entry_point: Optional entry point node ID (auto-detected if not provided)
        max_iterations: Maximum loop iterations per node (default 10)
    """

    name: str
    nodes: List[NodeConfig]
    edges: List[EdgeDefinition]
    entry_point: Optional[str] = None
    max_iterations: int = 10

    def __post_init__(self):
        """Validate workflow definition."""
        if not self.name:
            raise ValueError("workflow name cannot be empty")
        if not self.nodes:
            raise ValueError("workflow must have at least one node")

        # Validate node IDs are unique
        node_ids = [node.id for node in self.nodes]
        if len(node_ids) != len(set(node_ids)):
            duplicates = [nid for nid in node_ids if node_ids.count(nid) > 1]
            raise ValueError(f"duplicate node IDs found: {set(duplicates)}")

        # Validate edge IDs are unique
        edge_ids = [edge.id for edge in self.edges]
        if len(edge_ids) != len(set(edge_ids)):
            duplicates = [eid for eid in edge_ids if edge_ids.count(eid) > 1]
            raise ValueError(f"duplicate edge IDs found: {set(duplicates)}")

        # Validate edges reference existing nodes
        for edge in self.edges:
            if edge.source not in node_ids:
                raise ValueError(f"edge {edge.id}: source node '{edge.source}' not found")
            if edge.target not in node_ids and edge.target != END:
                raise ValueError(f"edge {edge.id}: target node '{edge.target}' not found")

        # Auto-detect entry point if not provided
        if self.entry_point is None:
            self.entry_point = self._detect_entry_point()
        elif self.entry_point not in node_ids:
            raise ValueError(f"entry_point '{self.entry_point}' not found in nodes")

    def _detect_entry_point(self) -> str:
        """Auto-detect entry point (node with no incoming edges)."""
        node_ids = {node.id for node in self.nodes}
        target_ids = {edge.target for edge in self.edges if edge.target != END}
        entry_candidates = node_ids - target_ids

        if not entry_candidates:
            # All nodes have incoming edges - potential circular dependency
            # Return first node as fallback
            return self.nodes[0].id

        if len(entry_candidates) == 1:
            return list(entry_candidates)[0]

        # Multiple entry points - return first one
        return list(entry_candidates)[0]


class ValidationError:
    """Workflow validation error.

    Attributes:
        code: Error code
        message: Error message
        severity: Error severity (error or warning)
        node_ids: List of affected node IDs
        context: Additional error context
    """

    def __init__(
        self,
        code: str,
        message: str,
        severity: str,
        node_ids: List[str],
        context: Dict[str, Any],
    ):
        self.code = code
        self.message = message
        self.severity = severity
        self.node_ids = node_ids
        self.context = context

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary format."""
        return {
            "code": self.code,
            "message": self.message,
            "severity": self.severity,
            "node_ids": self.node_ids,
            "context": self.context,
        }


class ValidationResult:
    """Workflow validation result.

    Attributes:
        valid: Whether workflow is valid
        errors: List of validation errors
        warnings: List of validation warnings
    """

    def __init__(self, valid: bool, errors: List[ValidationError], warnings: List[ValidationError]):
        self.valid = valid
        self.errors = errors
        self.warnings = warnings

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary format."""
        return {
            "valid": self.valid,
            "errors": [e.to_dict() for e in self.errors],
            "warnings": [w.to_dict() for w in self.warnings],
        }


def validate_workflow(workflow: WorkflowDefinition) -> ValidationResult:
    """Validate workflow configuration.

    This function performs comprehensive validation including:
    - Circular dependency detection
    - Node type validation
    - Node configuration validation
    - Dangling node detection

    Args:
        workflow: Workflow definition to validate

    Returns:
        ValidationResult containing validation status and errors/warnings
    """
    errors = []
    warnings = []

    # 1. Validate node types are registered
    for node in workflow.nodes:
        if not is_node_type_registered(node.type):
            errors.append(
                ValidationError(
                    code="INVALID_NODE_TYPE",
                    message=f"Node {node.id} has unregistered type '{node.type}'",
                    severity="error",
                    node_ids=[node.id],
                    context={"node_type": node.type},
                )
            )

    # 2. Detect loops — controlled loops (with condition exit) are allowed
    loops = detect_loops(workflow)
    for loop in loops:
        if loop.has_condition_exit:
            # Controlled loop — produce warning, not error
            cycle_str = " → ".join(loop.cycle_path)
            warnings.append(
                ValidationError(
                    code="CONTROLLED_LOOP",
                    message=f"检测到受控循环：{cycle_str}（由 condition 节点 '{loop.condition_node_id}' 控制退出，最大迭代 {workflow.max_iterations} 次）",
                    severity="warning",
                    node_ids=loop.cycle_path[:-1],
                    context={
                        "cycle_path": loop.cycle_path,
                        "condition_node_id": loop.condition_node_id,
                        "max_iterations": workflow.max_iterations,
                    },
                )
            )
        else:
            # Uncontrolled loop — error
            cycle_str = " → ".join(loop.cycle_path)
            errors.append(
                ValidationError(
                    code="CIRCULAR_DEPENDENCY",
                    message=f"检测到无出口环路：{cycle_str}（循环路径中需要 condition 节点控制退出）",
                    severity="error",
                    node_ids=loop.cycle_path[:-1],
                    context={"cycle_path": loop.cycle_path},
                )
            )

    # 3. Validate node configurations
    for node in workflow.nodes:
        if is_node_type_registered(node.type):
            try:
                node_instance = create_node(node.id, node.type, node.config)
                validation_errors = node_instance.validate_config()
                if validation_errors:
                    errors.append(
                        ValidationError(
                            code="INVALID_NODE_CONFIG",
                            message=f"节点 {node.id} 配置无效",
                            severity="error",
                            node_ids=[node.id],
                            context={
                                "node_type": node.type,
                                "validation_errors": validation_errors,
                            },
                        )
                    )
            except Exception as e:
                logger.error(f"Failed to validate node {node.id}: {e}")

    # 4. Detect dangling nodes (no incoming or outgoing edges)
    dangling_nodes = detect_dangling_nodes(workflow)
    for node_id in dangling_nodes:
        warnings.append(
            ValidationError(
                code="DANGLING_NODE",
                message=f"节点 {node_id} 未连接到工作流",
                severity="warning",
                node_ids=[node_id],
                context={
                    "connection_suggestions": _get_connection_suggestions(workflow, node_id)
                },
            )
        )

    # 5. Detect nodes with no outgoing edges (potential dead ends)
    node_ids = {node.id for node in workflow.nodes}
    sources = {edge.source for edge in workflow.edges}
    for node_id in node_ids - sources:
        # Skip if already flagged as dangling
        if node_id not in dangling_nodes:
            warnings.append(
                ValidationError(
                    code="NO_OUTGOING_EDGE",
                    message=f"节点 '{node_id}' 无出边（可能是终止节点，请确认）",
                    severity="warning",
                    node_ids=[node_id],
                    context={},
                )
            )

    # 6. Validate conditional edge expressions
    for edge in workflow.edges:
        if edge.condition:
            expr_errors = validate_condition_expression(edge.condition)
            for err in expr_errors:
                errors.append(
                    ValidationError(
                        code="INVALID_CONDITION",
                        message=f"边 {edge.id} 的条件表达式无效：{err}",
                        severity="error",
                        node_ids=[edge.source, edge.target],
                        context={"edge_id": edge.id, "condition": edge.condition},
                    )
                )

    # 7. Validate conditional edge consistency (same source should cover true/false)
    conditional_sources: Dict[str, List[EdgeDefinition]] = defaultdict(list)
    for edge in workflow.edges:
        if edge.condition:
            conditional_sources[edge.source].append(edge)
    for source_id, cond_edges in conditional_sources.items():
        unconditional = [e for e in workflow.edges if e.source == source_id and not e.condition]
        if unconditional:
            warnings.append(
                ValidationError(
                    code="MIXED_EDGE_TYPES",
                    message=f"节点 '{source_id}' 同时拥有条件边和非条件边，可能导致意外路由",
                    severity="warning",
                    node_ids=[source_id],
                    context={
                        "conditional_edges": [e.id for e in cond_edges],
                        "unconditional_edges": [e.id for e in unconditional],
                    },
                )
            )

    valid = len(errors) == 0
    return ValidationResult(valid=valid, errors=errors, warnings=warnings)


@dataclass
class LoopInfo:
    """Information about a detected loop in the workflow.

    Attributes:
        cycle_path: List of node IDs forming the loop (last == first)
        has_condition_exit: Whether a condition node controls the loop exit
        condition_node_id: ID of the condition node that controls the exit (if any)
    """
    cycle_path: List[str]
    has_condition_exit: bool = False
    condition_node_id: Optional[str] = None


def detect_loops(workflow: WorkflowDefinition) -> List[LoopInfo]:
    """Detect all loops in the workflow using DFS.

    Unlike the old detect_circular_dependency, this returns structured loop
    information instead of a single error, enabling controlled loops.

    Args:
        workflow: Workflow definition

    Returns:
        List of LoopInfo for each detected loop
    """
    # Build adjacency list and edge map
    graph = defaultdict(list)
    edge_map: Dict[Tuple[str, str], EdgeDefinition] = {}
    for edge in workflow.edges:
        if edge.target != END:
            graph[edge.source].append(edge.target)
            edge_map[(edge.source, edge.target)] = edge

    # Collect node types for condition detection
    node_types = {node.id: node.type for node in workflow.nodes}

    # DFS to find all cycles
    loops: List[LoopInfo] = []
    visited: Set[str] = set()
    path: List[str] = []
    path_set: Set[str] = set()
    found_cycles: Set[tuple] = set()  # Deduplicate cycles

    def dfs(node: str):
        if node in path_set:
            cycle_start_idx = path.index(node)
            cycle_path = path[cycle_start_idx:] + [node]
            # Normalize cycle for dedup (rotate to smallest element first)
            cycle_nodes = tuple(sorted(cycle_path[:-1]))
            if cycle_nodes not in found_cycles:
                found_cycles.add(cycle_nodes)
                # Check if any node in the cycle is a condition node with an exit edge
                has_exit = False
                exit_node = None
                for i, nid in enumerate(cycle_path[:-1]):
                    if node_types.get(nid) == "condition":
                        # Check if this condition node has an edge going outside the loop
                        cycle_node_set = set(cycle_path[:-1])
                        for neighbor in graph[nid]:
                            if neighbor not in cycle_node_set or neighbor == END:
                                has_exit = True
                                exit_node = nid
                                break
                        # Also check edges with condition expressions going to END
                        for edge in workflow.edges:
                            if edge.source == nid and (edge.target == END or edge.target not in cycle_node_set):
                                has_exit = True
                                exit_node = nid
                                break
                    if has_exit:
                        break
                loops.append(LoopInfo(
                    cycle_path=cycle_path,
                    has_condition_exit=has_exit,
                    condition_node_id=exit_node,
                ))
            return

        if node in visited:
            return

        visited.add(node)
        path.append(node)
        path_set.add(node)

        for neighbor in graph[node]:
            dfs(neighbor)

        path.pop()
        path_set.remove(node)

    for node in workflow.nodes:
        if node.id not in visited:
            dfs(node.id)

    return loops


def detect_circular_dependency(workflow: WorkflowDefinition) -> Optional[ValidationError]:
    """Detect circular dependencies using DFS.

    Legacy wrapper around detect_loops for backward compatibility.

    Args:
        workflow: Workflow definition

    Returns:
        ValidationError if uncontrolled cycle detected, None otherwise
    """
    loops = detect_loops(workflow)
    for loop in loops:
        if not loop.has_condition_exit:
            cycle_str = " → ".join(loop.cycle_path)
            return ValidationError(
                code="CIRCULAR_DEPENDENCY",
                message=f"检测到无出口环路：{cycle_str}（循环路径中需要 condition 节点控制退出）",
                severity="error",
                node_ids=loop.cycle_path[:-1],
                context={"cycle_path": loop.cycle_path},
            )
    return None


def detect_dangling_nodes(workflow: WorkflowDefinition) -> List[str]:
    """Detect nodes with no incoming or outgoing edges.

    Args:
        workflow: Workflow definition

    Returns:
        List of dangling node IDs
    """
    node_ids = {node.id for node in workflow.nodes}
    connected_nodes = set()

    for edge in workflow.edges:
        connected_nodes.add(edge.source)
        if edge.target != END:
            connected_nodes.add(edge.target)

    dangling = list(node_ids - connected_nodes)
    return dangling


def _get_connection_suggestions(workflow: WorkflowDefinition, node_id: str) -> List[str]:
    """Get connection suggestions for a dangling node."""
    suggestions = []
    for node in workflow.nodes:
        if node.id != node_id:
            node_name = node.config.get("name", node.id)
            suggestions.append(f"连接到 {node.id}（{node_name}）")
    return suggestions[:2]  # Return top 2 suggestions


def topological_sort(workflow: WorkflowDefinition) -> List[str]:
    """Perform topological sort on workflow nodes.

    For DAGs, returns standard topological order.
    For workflows with controlled loops (condition-gated cycles),
    sorts non-loop nodes first, then appends loop nodes in discovery order.

    Args:
        workflow: Workflow definition

    Returns:
        List of node IDs in execution order

    Raises:
        ValueError: If workflow contains uncontrolled cycles (no condition exit)
    """
    # Build adjacency list and in-degree count
    graph = defaultdict(list)
    in_degree = {node.id: 0 for node in workflow.nodes}

    for edge in workflow.edges:
        if edge.target != END:
            graph[edge.source].append(edge.target)
            in_degree[edge.target] += 1

    # Kahn's algorithm
    queue = deque([node_id for node_id, degree in in_degree.items() if degree == 0])
    result = []

    while queue:
        node_id = queue.popleft()
        result.append(node_id)

        for neighbor in graph[node_id]:
            in_degree[neighbor] -= 1
            if in_degree[neighbor] == 0:
                queue.append(neighbor)

    if len(result) == len(workflow.nodes):
        return result

    # Some nodes not sorted — check if they form controlled loops
    loops = detect_loops(workflow)
    has_uncontrolled = any(not loop.has_condition_exit for loop in loops)
    if has_uncontrolled:
        raise ValueError("Workflow contains uncontrolled cycles - cannot perform topological sort")

    # Controlled loops: append remaining nodes in discovery order
    sorted_set = set(result)
    remaining = [node.id for node in workflow.nodes if node.id not in sorted_set]
    result.extend(remaining)
    return result


def build_graph_from_config(workflow: WorkflowDefinition):
    """Build LangGraph StateGraph from workflow configuration.

    Args:
        workflow: Workflow definition

    Returns:
        Compiled LangGraph StateGraph

    Raises:
        ValueError: If workflow is invalid
        ImportError: If langgraph is not installed

    Example:
        workflow = WorkflowDefinition(
            name="my_workflow",
            nodes=[
                NodeConfig(id="node-1", type="data_source", config={...}),
                NodeConfig(id="node-2", type="data_processor", config={...}),
            ],
            edges=[
                EdgeDefinition(id="edge-1", source="node-1", target="node-2"),
            ]
        )
        graph = build_graph_from_config(workflow)
        result = await graph.ainvoke(initial_state)
    """
    if not LANGGRAPH_AVAILABLE:
        raise ImportError(
            "langgraph is required for build_graph_from_config(). "
            "Install it with: pip install langgraph"
        )

    # Validate workflow first
    validation_result = validate_workflow(workflow)
    if not validation_result.valid:
        error_messages = [e.message for e in validation_result.errors]
        raise ValueError(f"Workflow validation failed: {'; '.join(error_messages)}")

    # Create state graph
    # For now, use a simple dict state type
    graph = StateGraph(dict)

    # Create node instances and add to graph
    node_instances = {}
    for node_config in workflow.nodes:
        node = create_node(node_config.id, node_config.type, node_config.config)
        node_instances[node_config.id] = node

        # Wrap node execute in a function that updates state
        def make_node_func(node_instance):
            async def node_func(state: Dict[str, Any]) -> Dict[str, Any]:
                # Execute node with current state as inputs
                result = await node_instance.execute(state)
                # Return result to merge into state
                return {node_instance.node_id: result}

            return node_func

        node_func = make_node_func(node)
        graph.add_node(node_config.id, node_func)

    # Set entry point
    graph.set_entry_point(workflow.entry_point)

    # Group edges by source to detect conditional branching
    edges_by_source: Dict[str, List[EdgeDefinition]] = defaultdict(list)
    for edge in workflow.edges:
        edges_by_source[edge.source].append(edge)

    # Add edges - handle conditional and unconditional separately
    for source_id, source_edges in edges_by_source.items():
        conditional_edges = [e for e in source_edges if e.condition]
        unconditional_edges = [e for e in source_edges if not e.condition]

        if conditional_edges:
            # Build conditional routing for this source node
            _add_conditional_edges(
                graph, source_id, conditional_edges, unconditional_edges,
                node_instances, workflow,
            )
        else:
            # All edges from this source are unconditional
            for edge in unconditional_edges:
                if edge.target == END:
                    graph.add_edge(source_id, END)
                else:
                    graph.add_edge(source_id, edge.target)

    # Compile with recursion_limit for loop support
    # LangGraph recursion_limit controls max steps across the entire graph
    # For loops: max_iterations * number_of_nodes_in_loop + non-loop steps
    loops = detect_loops(workflow)
    if loops:
        recursion_limit = workflow.max_iterations * len(workflow.nodes) + len(workflow.nodes)
        logger.info(
            f"Workflow has {len(loops)} loop(s), setting recursion_limit={recursion_limit} "
            f"(max_iterations={workflow.max_iterations})"
        )
        return graph.compile(recursion_limit=recursion_limit)

    return graph.compile()


def _add_conditional_edges(
    graph,
    source_id: str,
    conditional_edges: List[EdgeDefinition],
    unconditional_edges: List[EdgeDefinition],
    node_instances: Dict[str, Any],
    workflow: WorkflowDefinition,
) -> None:
    """Add conditional edges from a source node using LangGraph's conditional routing.

    The routing function evaluates each edge's condition expression against
    the current workflow state. The first matching condition determines the target.

    If no condition matches and there's an unconditional edge, it serves as the
    default/fallback route. If no unconditional edge exists and nothing matches,
    the workflow ends.

    Args:
        graph: The StateGraph being built
        source_id: The source node ID
        conditional_edges: Edges with condition expressions
        unconditional_edges: Edges without conditions (used as default)
        node_instances: Map of node ID to node instance
        workflow: The workflow definition
    """
    # Determine the default target (unconditional edge or END)
    default_target = END
    if unconditional_edges:
        default_target = unconditional_edges[0].target
        if len(unconditional_edges) > 1:
            logger.warning(
                f"Node '{source_id}' has multiple unconditional edges; "
                f"using '{default_target}' as default"
            )

    # Build path map: all possible targets
    path_map = {}
    for edge in conditional_edges:
        target = END if edge.target == END else edge.target
        path_map[edge.target] = target
    path_map["__default__"] = default_target

    # Create routing function
    def make_router(src_id, cond_edges, default):
        def router(state: Dict[str, Any]) -> str:
            """Evaluate conditions and return the target node ID."""
            # Build evaluation context from full state
            # The source node's output is available as state[source_id]
            node_output = state.get(src_id, {})

            # Try each conditional edge in order
            for edge in cond_edges:
                try:
                    # Build context: merge state with source node output for convenience
                    context = {**state}
                    if isinstance(node_output, dict):
                        context["result"] = node_output
                        # Also expose condition_result directly for condition nodes
                        if "condition_result" in node_output:
                            context["condition_result"] = node_output["condition_result"]
                        if "branch_taken" in node_output:
                            context["branch_taken"] = node_output["branch_taken"]

                    result = safe_eval(edge.condition, context)
                    if result:
                        logger.info(
                            f"Conditional route: {src_id} -> {edge.target} "
                            f"(condition '{edge.condition}' = True)"
                        )
                        return edge.target
                except SafeEvalError as e:
                    logger.error(
                        f"Condition evaluation failed for edge {edge.id}: {e}. "
                        f"Skipping this condition."
                    )
                    continue

            # No condition matched - use default
            logger.info(
                f"Conditional route: {src_id} -> {default} (no condition matched, using default)"
            )
            return "__default__"

        return router

    routing_func = make_router(source_id, conditional_edges, default_target)
    graph.add_conditional_edges(source_id, routing_func, path_map)


def get_execution_order(workflow: WorkflowDefinition) -> List[str]:
    """Get the execution order of nodes in the workflow.

    Args:
        workflow: Workflow definition

    Returns:
        List of node IDs in execution order (topological sort)
    """
    return topological_sort(workflow)
