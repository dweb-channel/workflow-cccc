"""Unit tests for Dynamic Graph Builder

Tests cover:
- WorkflowDefinition creation and validation
- Circular dependency detection
- Dangling node detection
- Topological sorting
- Graph building from Fixture v1.0 scenarios
"""

import pytest

from workflow.engine.graph_builder import (
    LANGGRAPH_AVAILABLE,
    EdgeDefinition,
    LoopInfo,
    NodeConfig,
    WorkflowDefinition,
    build_graph_from_config,
    detect_circular_dependency,
    detect_dangling_nodes,
    detect_loops,
    get_execution_order,
    topological_sort,
    validate_workflow,
)

# Import node types to ensure registration
from workflow.nodes.base import (
    DataProcessorNode,
    DataSourceNode,
    HttpRequestNode,
)


class TestNodeConfig:
    """Test NodeConfig dataclass."""

    def test_valid_node_config(self):
        """Test creating valid node config."""
        node = NodeConfig(
            id="node-1",
            type="data_source",
            config={"name": "Test Source"}
        )

        assert node.id == "node-1"
        assert node.type == "data_source"
        assert node.config["name"] == "Test Source"

    def test_node_config_empty_id(self):
        """Test that empty ID raises ValueError."""
        with pytest.raises(ValueError, match="node id cannot be empty"):
            NodeConfig(id="", type="data_source", config={})

    def test_node_config_empty_type(self):
        """Test that empty type raises ValueError."""
        with pytest.raises(ValueError, match="node type cannot be empty"):
            NodeConfig(id="node-1", type="", config={})


class TestEdgeDefinition:
    """Test EdgeDefinition dataclass."""

    def test_valid_edge(self):
        """Test creating valid edge."""
        edge = EdgeDefinition(
            id="edge-1",
            source="node-1",
            target="node-2"
        )

        assert edge.id == "edge-1"
        assert edge.source == "node-1"
        assert edge.target == "node-2"
        assert edge.condition is None

    def test_edge_with_condition(self):
        """Test edge with condition."""
        edge = EdgeDefinition(
            id="edge-1",
            source="node-1",
            target="node-2",
            condition="value > 100"
        )

        assert edge.condition == "value > 100"

    def test_edge_self_loop(self):
        """Test that self-loop raises ValueError."""
        with pytest.raises(ValueError, match="self-loop detected"):
            EdgeDefinition(id="edge-1", source="node-1", target="node-1")


class TestWorkflowDefinition:
    """Test WorkflowDefinition dataclass."""

    def test_valid_workflow(self):
        """Test creating valid workflow."""
        workflow = WorkflowDefinition(
            name="test_workflow",
            nodes=[
                NodeConfig(id="node-1", type="data_source", config={"name": "Source"}),
                NodeConfig(id="node-2", type="data_processor", config={"name": "Processor", "input_field": "{{node-1.data}}"}),
            ],
            edges=[
                EdgeDefinition(id="edge-1", source="node-1", target="node-2"),
            ]
        )

        assert workflow.name == "test_workflow"
        assert len(workflow.nodes) == 2
        assert len(workflow.edges) == 1
        assert workflow.entry_point == "node-1"  # Auto-detected

    def test_workflow_explicit_entry_point(self):
        """Test workflow with explicit entry point."""
        workflow = WorkflowDefinition(
            name="test_workflow",
            nodes=[
                NodeConfig(id="node-1", type="data_source", config={"name": "Source"}),
            ],
            edges=[],
            entry_point="node-1"
        )

        assert workflow.entry_point == "node-1"

    def test_workflow_duplicate_node_ids(self):
        """Test that duplicate node IDs raise ValueError."""
        with pytest.raises(ValueError, match="duplicate node IDs"):
            WorkflowDefinition(
                name="test",
                nodes=[
                    NodeConfig(id="node-1", type="data_source", config={}),
                    NodeConfig(id="node-1", type="data_processor", config={"name": "P", "input_field": "x"}),
                ],
                edges=[]
            )

    def test_workflow_edge_references_nonexistent_node(self):
        """Test that edge referencing nonexistent node raises ValueError."""
        with pytest.raises(ValueError, match="source node .* not found"):
            WorkflowDefinition(
                name="test",
                nodes=[
                    NodeConfig(id="node-1", type="data_source", config={}),
                ],
                edges=[
                    EdgeDefinition(id="edge-1", source="nonexistent", target="node-1"),
                ]
            )


class TestCircularDependencyDetection:
    """Test circular dependency detection."""

    def test_detect_circular_dependency_simple_cycle(self):
        """Test detecting simple 3-node cycle (Fixture: circular_dependency)."""
        workflow = WorkflowDefinition(
            name="circular_dependency_test",
            nodes=[
                NodeConfig(id="node-1", type="data_processor", config={"name": "A", "input_field": "{{node-3.result}}"}),
                NodeConfig(id="node-2", type="data_processor", config={"name": "B", "input_field": "{{node-1.result}}"}),
                NodeConfig(id="node-3", type="data_processor", config={"name": "C", "input_field": "{{node-2.result}}"}),
            ],
            edges=[
                EdgeDefinition(id="edge-1", source="node-3", target="node-1"),
                EdgeDefinition(id="edge-2", source="node-1", target="node-2"),
                EdgeDefinition(id="edge-3", source="node-2", target="node-3"),
            ]
        )

        error = detect_circular_dependency(workflow)

        assert error is not None
        assert error.code == "CIRCULAR_DEPENDENCY"
        assert len(error.node_ids) == 3
        assert error.context["cycle_path"] == ["node-1", "node-2", "node-3", "node-1"]

    def test_no_circular_dependency(self):
        """Test workflow without circular dependency."""
        workflow = WorkflowDefinition(
            name="no_cycle",
            nodes=[
                NodeConfig(id="node-1", type="data_source", config={"name": "Source"}),
                NodeConfig(id="node-2", type="data_processor", config={"name": "Processor", "input_field": "{{node-1.data}}"}),
            ],
            edges=[
                EdgeDefinition(id="edge-1", source="node-1", target="node-2"),
            ]
        )

        error = detect_circular_dependency(workflow)
        assert error is None


class TestDanglingNodeDetection:
    """Test dangling node detection."""

    def test_detect_dangling_node(self):
        """Test detecting dangling nodes (Fixture: dangling_node)."""
        workflow = WorkflowDefinition(
            name="dangling_node_test",
            nodes=[
                NodeConfig(id="node-1", type="data_source", config={"name": "Source"}),
                NodeConfig(id="node-2", type="data_processor", config={"name": "Processor", "input_field": "x"}),
                NodeConfig(id="node-3", type="data_processor", config={"name": "Isolated", "input_field": "y"}),
            ],
            edges=[
                EdgeDefinition(id="edge-1", source="node-1", target="node-2"),
            ]
        )

        dangling = detect_dangling_nodes(workflow)

        assert len(dangling) == 1
        assert "node-3" in dangling

    def test_no_dangling_nodes(self):
        """Test workflow with no dangling nodes."""
        workflow = WorkflowDefinition(
            name="connected",
            nodes=[
                NodeConfig(id="node-1", type="data_source", config={"name": "Source"}),
                NodeConfig(id="node-2", type="data_processor", config={"name": "Processor", "input_field": "{{node-1.data}}"}),
            ],
            edges=[
                EdgeDefinition(id="edge-1", source="node-1", target="node-2"),
            ]
        )

        dangling = detect_dangling_nodes(workflow)
        assert len(dangling) == 0


class TestTopologicalSort:
    """Test topological sorting."""

    def test_topological_sort_linear(self):
        """Test topological sort on linear workflow."""
        workflow = WorkflowDefinition(
            name="linear",
            nodes=[
                NodeConfig(id="node-1", type="data_source", config={"name": "Source"}),
                NodeConfig(id="node-2", type="data_processor", config={"name": "P1", "input_field": "x"}),
                NodeConfig(id="node-3", type="data_processor", config={"name": "P2", "input_field": "y"}),
            ],
            edges=[
                EdgeDefinition(id="edge-1", source="node-1", target="node-2"),
                EdgeDefinition(id="edge-2", source="node-2", target="node-3"),
            ]
        )

        order = topological_sort(workflow)

        assert order == ["node-1", "node-2", "node-3"]

    def test_topological_sort_dag(self):
        """Test topological sort on DAG workflow."""
        workflow = WorkflowDefinition(
            name="dag",
            nodes=[
                NodeConfig(id="node-1", type="data_source", config={"name": "Source"}),
                NodeConfig(id="node-2", type="data_processor", config={"name": "P1", "input_field": "x"}),
                NodeConfig(id="node-3", type="data_processor", config={"name": "P2", "input_field": "y"}),
                NodeConfig(id="node-4", type="data_processor", config={"name": "P3", "input_field": "z"}),
            ],
            edges=[
                EdgeDefinition(id="edge-1", source="node-1", target="node-2"),
                EdgeDefinition(id="edge-2", source="node-1", target="node-3"),
                EdgeDefinition(id="edge-3", source="node-2", target="node-4"),
                EdgeDefinition(id="edge-4", source="node-3", target="node-4"),
            ]
        )

        order = topological_sort(workflow)

        # Verify node-1 comes before all others
        assert order[0] == "node-1"
        # Verify node-4 comes last
        assert order[-1] == "node-4"
        # Verify node-2 and node-3 come after node-1 and before node-4
        assert order.index("node-2") > order.index("node-1")
        assert order.index("node-3") > order.index("node-1")
        assert order.index("node-2") < order.index("node-4")
        assert order.index("node-3") < order.index("node-4")

    def test_topological_sort_with_cycle(self):
        """Test that topological sort raises error on cycle."""
        workflow = WorkflowDefinition(
            name="cycle",
            nodes=[
                NodeConfig(id="node-1", type="data_processor", config={"name": "A", "input_field": "{{node-3.result}}"}),
                NodeConfig(id="node-2", type="data_processor", config={"name": "B", "input_field": "{{node-1.result}}"}),
                NodeConfig(id="node-3", type="data_processor", config={"name": "C", "input_field": "{{node-2.result}}"}),
            ],
            edges=[
                EdgeDefinition(id="edge-1", source="node-3", target="node-1"),
                EdgeDefinition(id="edge-2", source="node-1", target="node-2"),
                EdgeDefinition(id="edge-3", source="node-2", target="node-3"),
            ]
        )

        with pytest.raises(ValueError, match="uncontrolled cycles"):
            topological_sort(workflow)


class TestWorkflowValidation:
    """Test workflow validation."""

    def test_validate_valid_workflow(self):
        """Test validation of valid workflow."""
        workflow = WorkflowDefinition(
            name="valid",
            nodes=[
                NodeConfig(id="node-1", type="data_source", config={"name": "Source"}),
                NodeConfig(id="node-2", type="data_processor", config={"name": "Processor", "input_field": "{{node-1.data}}"}),
            ],
            edges=[
                EdgeDefinition(id="edge-1", source="node-1", target="node-2"),
            ]
        )

        result = validate_workflow(workflow)

        assert result.valid is True
        assert len(result.errors) == 0
        # node-2 has no outgoing edge, which produces a warning (not an error)
        no_outgoing = [w for w in result.warnings if w.code == "NO_OUTGOING_EDGE"]
        assert len(no_outgoing) == 1
        assert "node-2" in no_outgoing[0].node_ids

    def test_validate_circular_dependency(self):
        """Test validation detects circular dependency."""
        workflow = WorkflowDefinition(
            name="cycle",
            nodes=[
                NodeConfig(id="node-1", type="data_processor", config={"name": "A", "input_field": "{{node-3.result}}"}),
                NodeConfig(id="node-2", type="data_processor", config={"name": "B", "input_field": "{{node-1.result}}"}),
                NodeConfig(id="node-3", type="data_processor", config={"name": "C", "input_field": "{{node-2.result}}"}),
            ],
            edges=[
                EdgeDefinition(id="edge-1", source="node-3", target="node-1"),
                EdgeDefinition(id="edge-2", source="node-1", target="node-2"),
                EdgeDefinition(id="edge-3", source="node-2", target="node-3"),
            ]
        )

        result = validate_workflow(workflow)

        assert result.valid is False
        assert len(result.errors) == 1
        assert result.errors[0].code == "CIRCULAR_DEPENDENCY"

    def test_validate_invalid_node_config(self):
        """Test validation detects invalid node configuration."""
        workflow = WorkflowDefinition(
            name="invalid_config",
            nodes=[
                NodeConfig(
                    id="node-1",
                    type="http_request",
                    config={
                        "name": "API",
                        "url": "not-a-valid-url",
                        "method": "INVALID",
                    }
                ),
            ],
            edges=[]
        )

        result = validate_workflow(workflow)

        assert result.valid is False
        errors = [e for e in result.errors if e.code == "INVALID_NODE_CONFIG"]
        assert len(errors) == 1
        assert errors[0].node_ids == ["node-1"]

    def test_validate_dangling_node_warning(self):
        """Test validation detects dangling nodes as warnings."""
        workflow = WorkflowDefinition(
            name="dangling",
            nodes=[
                NodeConfig(id="node-1", type="data_source", config={"name": "Source"}),
                NodeConfig(id="node-2", type="data_processor", config={"name": "Processor", "input_field": "x"}),
                NodeConfig(id="node-3", type="data_processor", config={"name": "Isolated", "input_field": "y"}),
            ],
            edges=[
                EdgeDefinition(id="edge-1", source="node-1", target="node-2"),
            ]
        )

        result = validate_workflow(workflow)

        assert result.valid is True  # Warnings don't make workflow invalid
        dangling = [w for w in result.warnings if w.code == "DANGLING_NODE"]
        assert len(dangling) == 1
        assert dangling[0].node_ids == ["node-3"]
        # node-2 also has no outgoing edge
        no_outgoing = [w for w in result.warnings if w.code == "NO_OUTGOING_EDGE"]
        assert len(no_outgoing) == 1
        assert "node-2" in no_outgoing[0].node_ids


@pytest.mark.skipif(not LANGGRAPH_AVAILABLE, reason="langgraph not installed")
class TestGraphBuilding:
    """Test graph building from configuration (requires langgraph)."""

    def test_build_simple_graph(self):
        """Test building simple 2-node workflow."""
        workflow = WorkflowDefinition(
            name="simple",
            nodes=[
                NodeConfig(id="node-1", type="data_source", config={"name": "Source", "output_schema": {"data": "string"}}),
                NodeConfig(id="node-2", type="data_processor", config={"name": "Processor", "input_field": "{{node-1.data}}"}),
            ],
            edges=[
                EdgeDefinition(id="edge-1", source="node-1", target="node-2"),
            ]
        )

        graph = build_graph_from_config(workflow)

        assert graph is not None

    def test_build_graph_with_invalid_workflow(self):
        """Test that building graph with invalid workflow raises error."""
        workflow = WorkflowDefinition(
            name="invalid",
            nodes=[
                NodeConfig(id="node-1", type="data_processor", config={"name": "A", "input_field": "{{node-3.result}}"}),
                NodeConfig(id="node-2", type="data_processor", config={"name": "B", "input_field": "{{node-1.result}}"}),
                NodeConfig(id="node-3", type="data_processor", config={"name": "C", "input_field": "{{node-2.result}}"}),
            ],
            edges=[
                EdgeDefinition(id="edge-1", source="node-3", target="node-1"),
                EdgeDefinition(id="edge-2", source="node-1", target="node-2"),
                EdgeDefinition(id="edge-3", source="node-2", target="node-3"),
            ]
        )

        with pytest.raises(ValueError, match="Workflow validation failed"):
            build_graph_from_config(workflow)


class TestExecutionOrder:
    """Test execution order (pure Python, no langgraph needed)."""

    def test_get_execution_order(self):
        """Test getting execution order."""
        workflow = WorkflowDefinition(
            name="ordered",
            nodes=[
                NodeConfig(id="node-1", type="data_source", config={"name": "Source"}),
                NodeConfig(id="node-2", type="data_processor", config={"name": "P1", "input_field": "x"}),
                NodeConfig(id="node-3", type="data_processor", config={"name": "P2", "input_field": "y"}),
            ],
            edges=[
                EdgeDefinition(id="edge-1", source="node-1", target="node-2"),
                EdgeDefinition(id="edge-2", source="node-2", target="node-3"),
            ]
        )

        order = get_execution_order(workflow)

        assert order == ["node-1", "node-2", "node-3"]


class TestLoopDetection:
    """Test loop detection and controlled loop support."""

    def test_detect_loops_no_loops(self):
        """Test detect_loops on DAG workflow returns empty list."""
        workflow = WorkflowDefinition(
            name="dag",
            nodes=[
                NodeConfig(id="node-1", type="data_source", config={"name": "Source"}),
                NodeConfig(id="node-2", type="data_processor", config={"name": "P", "input_field": "x"}),
            ],
            edges=[
                EdgeDefinition(id="edge-1", source="node-1", target="node-2"),
            ]
        )

        loops = detect_loops(workflow)
        assert len(loops) == 0

    def test_detect_loops_uncontrolled(self):
        """Test detect_loops finds uncontrolled cycle (no condition exit)."""
        workflow = WorkflowDefinition(
            name="uncontrolled_loop",
            nodes=[
                NodeConfig(id="node-1", type="data_processor", config={"name": "A", "input_field": "x"}),
                NodeConfig(id="node-2", type="data_processor", config={"name": "B", "input_field": "y"}),
                NodeConfig(id="node-3", type="data_processor", config={"name": "C", "input_field": "z"}),
            ],
            edges=[
                EdgeDefinition(id="edge-1", source="node-1", target="node-2"),
                EdgeDefinition(id="edge-2", source="node-2", target="node-3"),
                EdgeDefinition(id="edge-3", source="node-3", target="node-1"),
            ]
        )

        loops = detect_loops(workflow)
        assert len(loops) == 1
        assert loops[0].has_condition_exit is False
        assert loops[0].condition_node_id is None

    def test_detect_loops_controlled_with_condition(self):
        """Test detect_loops finds controlled loop with condition node exit."""
        workflow = WorkflowDefinition(
            name="controlled_loop",
            nodes=[
                NodeConfig(id="start", type="data_source", config={"name": "Start"}),
                NodeConfig(id="process", type="data_processor", config={"name": "Process", "input_field": "x"}),
                NodeConfig(id="check", type="condition", config={
                    "name": "Check",
                    "condition": "done == True",
                }),
                NodeConfig(id="output", type="output", config={"name": "Output", "format": "json"}),
            ],
            edges=[
                EdgeDefinition(id="edge-1", source="start", target="process"),
                EdgeDefinition(id="edge-2", source="process", target="check"),
                EdgeDefinition(id="edge-3", source="check", target="process", condition="done != True"),
                EdgeDefinition(id="edge-4", source="check", target="output", condition="done == True"),
            ]
        )

        loops = detect_loops(workflow)
        assert len(loops) == 1
        assert loops[0].has_condition_exit is True
        assert loops[0].condition_node_id == "check"

    def test_self_loop_still_rejected(self):
        """Test that self-loops are still rejected at EdgeDefinition level."""
        with pytest.raises(ValueError, match="self-loop detected"):
            EdgeDefinition(id="edge-1", source="node-1", target="node-1")

    def test_max_iterations_default(self):
        """Test WorkflowDefinition max_iterations defaults to 10."""
        workflow = WorkflowDefinition(
            name="test",
            nodes=[NodeConfig(id="n1", type="data_source", config={"name": "S"})],
            edges=[],
        )
        assert workflow.max_iterations == 10

    def test_max_iterations_custom(self):
        """Test WorkflowDefinition accepts custom max_iterations."""
        workflow = WorkflowDefinition(
            name="test",
            nodes=[NodeConfig(id="n1", type="data_source", config={"name": "S"})],
            edges=[],
            max_iterations=5,
        )
        assert workflow.max_iterations == 5

    def test_validate_controlled_loop_passes(self):
        """Test that validation passes for controlled loops (warning, not error)."""
        workflow = WorkflowDefinition(
            name="controlled_loop",
            nodes=[
                NodeConfig(id="start", type="data_source", config={"name": "Start"}),
                NodeConfig(id="process", type="data_processor", config={"name": "Process", "input_field": "x"}),
                NodeConfig(id="check", type="condition", config={
                    "name": "Check",
                    "condition": "done == True",
                }),
                NodeConfig(id="output", type="output", config={"name": "Output", "format": "json"}),
            ],
            edges=[
                EdgeDefinition(id="edge-1", source="start", target="process"),
                EdgeDefinition(id="edge-2", source="process", target="check"),
                EdgeDefinition(id="edge-3", source="check", target="process", condition="done != True"),
                EdgeDefinition(id="edge-4", source="check", target="output", condition="done == True"),
            ]
        )

        result = validate_workflow(workflow)
        assert result.valid is True
        # Should have a CONTROLLED_LOOP warning
        loop_warnings = [w for w in result.warnings if w.code == "CONTROLLED_LOOP"]
        assert len(loop_warnings) == 1
        assert "check" in loop_warnings[0].context["condition_node_id"]

    def test_validate_uncontrolled_loop_fails(self):
        """Test that validation fails for uncontrolled loops."""
        workflow = WorkflowDefinition(
            name="uncontrolled_loop",
            nodes=[
                NodeConfig(id="node-1", type="data_processor", config={"name": "A", "input_field": "x"}),
                NodeConfig(id="node-2", type="data_processor", config={"name": "B", "input_field": "y"}),
            ],
            edges=[
                EdgeDefinition(id="edge-1", source="node-1", target="node-2"),
                EdgeDefinition(id="edge-2", source="node-2", target="node-1"),
            ]
        )

        result = validate_workflow(workflow)
        assert result.valid is False
        circ_errors = [e for e in result.errors if e.code == "CIRCULAR_DEPENDENCY"]
        assert len(circ_errors) == 1

    def test_topological_sort_with_controlled_loop(self):
        """Test topological sort handles controlled loops gracefully."""
        workflow = WorkflowDefinition(
            name="controlled_loop",
            nodes=[
                NodeConfig(id="start", type="data_source", config={"name": "Start"}),
                NodeConfig(id="process", type="data_processor", config={"name": "Process", "input_field": "x"}),
                NodeConfig(id="check", type="condition", config={
                    "name": "Check",
                    "condition": "done == True",
                }),
                NodeConfig(id="output", type="output", config={"name": "Output", "format": "json"}),
            ],
            edges=[
                EdgeDefinition(id="edge-1", source="start", target="process"),
                EdgeDefinition(id="edge-2", source="process", target="check"),
                EdgeDefinition(id="edge-3", source="check", target="process", condition="done != True"),
                EdgeDefinition(id="edge-4", source="check", target="output", condition="done == True"),
            ]
        )

        order = topological_sort(workflow)
        # start should be first (only node with no incoming edges from non-loop edges)
        assert order[0] == "start"
        # All nodes should be present
        assert set(order) == {"start", "process", "check", "output"}

    def test_topological_sort_uncontrolled_loop_raises(self):
        """Test topological sort raises error for uncontrolled loops."""
        workflow = WorkflowDefinition(
            name="uncontrolled",
            nodes=[
                NodeConfig(id="node-1", type="data_processor", config={"name": "A", "input_field": "x"}),
                NodeConfig(id="node-2", type="data_processor", config={"name": "B", "input_field": "y"}),
            ],
            edges=[
                EdgeDefinition(id="edge-1", source="node-1", target="node-2"),
                EdgeDefinition(id="edge-2", source="node-2", target="node-1"),
            ]
        )

        with pytest.raises(ValueError, match="uncontrolled cycles"):
            topological_sort(workflow)

    def test_detect_circular_dependency_backward_compat(self):
        """Test legacy detect_circular_dependency allows controlled loops."""
        # Controlled loop — should return None (no error)
        workflow = WorkflowDefinition(
            name="controlled",
            nodes=[
                NodeConfig(id="process", type="data_processor", config={"name": "P", "input_field": "x"}),
                NodeConfig(id="check", type="condition", config={
                    "name": "Check",
                    "condition_expression": "True",
                }),
                NodeConfig(id="output", type="output", config={"name": "Out"}),
            ],
            edges=[
                EdgeDefinition(id="e1", source="process", target="check"),
                EdgeDefinition(id="e2", source="check", target="process", condition="not done"),
                EdgeDefinition(id="e3", source="check", target="output", condition="done"),
            ]
        )

        error = detect_circular_dependency(workflow)
        assert error is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
