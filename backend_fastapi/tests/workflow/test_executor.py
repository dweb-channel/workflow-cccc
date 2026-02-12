"""Unit tests for Dynamic Workflow Executor

Tests cover:
- Per-node execution counting
- MaxIterationsExceeded enforcement
- SSE event emissions (loop_iteration, loop_terminated)
- Graceful loop termination with partial results
"""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from collections import defaultdict

from workflow.engine.executor import (
    MaxIterationsExceeded,
    execute_dynamic_workflow,
)
from workflow.engine.graph_builder import (
    EdgeDefinition,
    NodeConfig,
    WorkflowDefinition,
)

# Import node types to ensure registration
import workflow.nodes.base  # noqa: F401


class TestMaxIterationsExceeded:
    """Test MaxIterationsExceeded exception."""

    def test_exception_attributes(self):
        exc = MaxIterationsExceeded("process", 11, 10)
        assert exc.node_id == "process"
        assert exc.count == 11
        assert exc.max_iterations == 10
        assert "process" in str(exc)
        assert "11/10" in str(exc)


class TestExecutorLoopControl:
    """Test executor loop execution control."""

    @pytest.fixture
    def controlled_loop_workflow(self):
        """A workflow with a controlled loop: start → process → check → process (loop) / output."""
        return WorkflowDefinition(
            name="controlled_loop_test",
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
                EdgeDefinition(id="e1", source="start", target="process"),
                EdgeDefinition(id="e2", source="process", target="check"),
                EdgeDefinition(id="e3", source="check", target="process", condition="done != True"),
                EdgeDefinition(id="e4", source="check", target="output", condition="done == True"),
            ],
            max_iterations=3,
        )

    @pytest.fixture
    def simple_workflow(self):
        """A simple DAG workflow with no loops."""
        return WorkflowDefinition(
            name="simple_test",
            nodes=[
                NodeConfig(id="node-1", type="data_source", config={"name": "Source"}),
                NodeConfig(id="node-2", type="data_processor", config={"name": "P", "input_field": "x"}),
            ],
            edges=[
                EdgeDefinition(id="e1", source="node-1", target="node-2"),
            ],
        )

    @pytest.mark.asyncio
    async def test_simple_workflow_no_loop_tracking(self, simple_workflow):
        """Test that simple DAG workflows don't trigger loop tracking."""
        # Mock the graph build and stream
        mock_graph = AsyncMock()

        async def fake_stream(state, config=None):
            yield {"node-1": {"data": "hello"}}
            yield {"node-2": {"result": "processed"}}

        mock_graph.astream = fake_stream

        with patch("workflow.engine.executor.build_graph_from_config", return_value=mock_graph), \
             patch("workflow.engine.executor.push_sse_event", new_callable=AsyncMock), \
             patch("workflow.engine.executor.notify_node_status", new_callable=AsyncMock):

            result = await execute_dynamic_workflow(simple_workflow, {}, run_id="test-run")

        assert result["success"] is True
        # node_execution_counts should show 1 each
        assert result["node_execution_counts"]["node-1"] == 1
        assert result["node_execution_counts"]["node-2"] == 1

    @pytest.mark.asyncio
    async def test_loop_iteration_counting(self, controlled_loop_workflow):
        """Test that loop nodes get their executions counted."""
        mock_graph = AsyncMock()

        # Simulate: start → process → check → process (loop) → check → output
        async def fake_stream(state, config=None):
            yield {"start": {"data": "init"}}
            yield {"process": {"result": "step1"}}
            yield {"check": {"condition_result": False}}
            yield {"process": {"result": "step2"}}  # Second iteration
            yield {"check": {"condition_result": True}}
            yield {"output": {"final": "done"}}

        mock_graph.astream = fake_stream

        with patch("workflow.engine.executor.build_graph_from_config", return_value=mock_graph), \
             patch("workflow.engine.executor.push_sse_event", new_callable=AsyncMock) as mock_sse, \
             patch("workflow.engine.executor.notify_node_status", new_callable=AsyncMock):

            result = await execute_dynamic_workflow(
                controlled_loop_workflow, {}, run_id="test-loop"
            )

        assert result["success"] is True
        assert result["node_execution_counts"]["process"] == 2
        assert result["node_execution_counts"]["check"] == 2

        # Verify loop_iteration SSE events were emitted
        loop_events = [
            call for call in mock_sse.call_args_list
            if call[0][1] == "loop_iteration"
        ]
        assert len(loop_events) >= 1  # At least one loop_iteration for process 2nd exec

    @pytest.mark.asyncio
    async def test_max_iterations_exceeded(self, controlled_loop_workflow):
        """Test that exceeding max_iterations terminates the loop gracefully."""
        mock_graph = AsyncMock()

        # Simulate infinite loop: process/check repeat > max_iterations (3)
        async def fake_stream(state, config=None):
            yield {"start": {"data": "init"}}
            for i in range(10):  # More than max_iterations=3
                yield {"process": {"result": f"step{i+1}"}}
                yield {"check": {"condition_result": False}}

        mock_graph.astream = fake_stream

        with patch("workflow.engine.executor.build_graph_from_config", return_value=mock_graph), \
             patch("workflow.engine.executor.push_sse_event", new_callable=AsyncMock) as mock_sse, \
             patch("workflow.engine.executor.notify_node_status", new_callable=AsyncMock):

            result = await execute_dynamic_workflow(
                controlled_loop_workflow, {}, run_id="test-max"
            )

        # Loop termination is not a hard error
        assert result["success"] is True
        assert result["loop_terminated"] is True
        assert result["loop_terminated_node"] in ("process", "check")

        # Verify loop_terminated SSE event was emitted
        terminated_events = [
            call for call in mock_sse.call_args_list
            if call[0][1] == "loop_terminated"
        ]
        assert len(terminated_events) == 1

    @pytest.mark.asyncio
    async def test_workflow_start_event_includes_loop_info(self, controlled_loop_workflow):
        """Test that workflow_start SSE event includes loop metadata."""
        mock_graph = AsyncMock()

        async def fake_stream(state, config=None):
            yield {"start": {"data": "init"}}

        mock_graph.astream = fake_stream

        with patch("workflow.engine.executor.build_graph_from_config", return_value=mock_graph), \
             patch("workflow.engine.executor.push_sse_event", new_callable=AsyncMock) as mock_sse, \
             patch("workflow.engine.executor.notify_node_status", new_callable=AsyncMock):

            await execute_dynamic_workflow(
                controlled_loop_workflow, {}, run_id="test-meta"
            )

        # Find workflow_start event
        start_events = [
            call for call in mock_sse.call_args_list
            if call[0][1] == "workflow_start"
        ]
        assert len(start_events) == 1
        start_data = start_events[0][0][2]
        assert start_data["has_loops"] is True
        assert start_data["max_iterations"] == 3

    @pytest.mark.asyncio
    async def test_workflow_complete_includes_execution_counts(self, simple_workflow):
        """Test that workflow_complete SSE event includes node_execution_counts."""
        mock_graph = AsyncMock()

        async def fake_stream(state, config=None):
            yield {"node-1": {"data": "hello"}}
            yield {"node-2": {"result": "done"}}

        mock_graph.astream = fake_stream

        with patch("workflow.engine.executor.build_graph_from_config", return_value=mock_graph), \
             patch("workflow.engine.executor.push_sse_event", new_callable=AsyncMock) as mock_sse, \
             patch("workflow.engine.executor.notify_node_status", new_callable=AsyncMock):

            await execute_dynamic_workflow(simple_workflow, {}, run_id="test-counts")

        complete_events = [
            call for call in mock_sse.call_args_list
            if call[0][1] == "workflow_complete"
        ]
        assert len(complete_events) == 1
        complete_data = complete_events[0][0][2]
        assert complete_data["node_execution_counts"] == {"node-1": 1, "node-2": 1}


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
