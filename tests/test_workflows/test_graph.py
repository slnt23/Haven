"""WorkflowGraph — DAG 执行引擎测试。"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest


class TestWorkflowGraphConstruction:
    """WorkflowGraph 构建 API 测试。"""

    @pytest.fixture
    def graph(self):
        from haven.workflows.graph import WorkflowGraph
        from haven.workflows.state import WorkflowState
        return WorkflowGraph(WorkflowState)

    def test_add_node(self, graph):
        graph.add_node("node1", MagicMock())
        assert "node1" in graph._nodes
        assert len(graph._nodes) == 1

    def test_add_edge(self, graph):
        graph.add_node("node1", MagicMock())
        graph.add_node("node2", MagicMock())
        result = graph.add_edge("node1", "node2")
        assert "node1" in graph._edges
        assert graph._edges["node1"].target == "node2"
        assert result is graph  # 链式调用

    def test_add_edge_duplicate_raises(self, graph):
        graph.add_node("node1", MagicMock())
        graph.add_node("node2", MagicMock())
        graph.add_edge("node1", "node2")
        with pytest.raises(ValueError):
            graph.add_edge("node1", "node3")

    def test_add_conditional_edge(self, graph):
        graph.add_node("node1", MagicMock())

        def router(state):
            return "target"

        result = graph.add_conditional_edge("node1", router)
        assert "node1" in graph._edges
        assert result is graph

    def test_set_entry_point(self, graph):
        node = MagicMock()
        graph.add_node("start", node)
        graph.set_entry_point("start")
        assert graph._entry_point == "start"

    def test_set_entry_point_unregistered_raises(self, graph):
        with pytest.raises(ValueError):
            graph.set_entry_point("not_there")

    def test_set_checkpointer(self, graph):
        from haven.workflows.checkpoint import SQLiteCheckpointer
        cp = SQLiteCheckpointer(db_path=":memory:")
        graph.set_checkpointer(cp)
        assert graph._checkpointer is cp


class TestWorkflowGraphRun:
    """WorkflowGraph.run() 执行测试。"""

    @pytest.fixture
    def graph_with_nodes(self, workflow_state):
        from haven.workflows.graph import WorkflowGraph
        from haven.workflows.state import WorkflowState

        graph = WorkflowGraph(WorkflowState)

        # 创建简单的线性图: start → middle → end
        node1 = _AsyncMockNode("start", "start output")
        node2 = _AsyncMockNode("middle", "middle output")
        node3 = _AsyncMockNode("end", "end output")

        graph.add_node("start", node1)
        graph.add_node("middle", node2)
        graph.add_node("end", node3)
        graph.add_edge("start", "middle")
        graph.add_edge("middle", "end")
        graph.set_entry_point("start")

        return graph

    @pytest.mark.asyncio
    async def test_run_linear_graph(self, graph_with_nodes, workflow_state, runtime_with_mock_llm):
        """线性 DAG 从头执行到尾。"""
        wf_state = workflow_state
        wf_state._runtime = runtime_with_mock_llm

        result = await graph_with_nodes.run(wf_state, runtime=runtime_with_mock_llm)

        assert result.execution.status == "completed"
        # 3 个节点都执行了
        assert "start" in result.node_outputs
        assert "middle" in result.node_outputs
        assert "end" in result.node_outputs

    @pytest.mark.asyncio
    async def test_run_records_execution_state(self, graph_with_nodes, workflow_state, runtime_with_mock_llm):
        """ExecutionState 记录执行过程。"""
        wf_state = workflow_state
        wf_state._runtime = runtime_with_mock_llm

        result = await graph_with_nodes.run(wf_state, runtime=runtime_with_mock_llm)

        es = result.execution
        assert es.status == "completed"
        assert len(es.completed_steps) == 0  # complete_step 不会被图中调用，除非 node 产生特定输出

    @pytest.mark.asyncio
    async def test_run_single_node(self, runtime_with_mock_llm):
        """单节点图 → 执行后立即结束。"""
        from haven.workflows.graph import WorkflowGraph
        from haven.workflows.state import WorkflowState

        graph = WorkflowGraph(WorkflowState)
        node = _AsyncMockNode("only", "done")
        graph.add_node("only", node)
        graph.set_entry_point("only")

        state = WorkflowState(task="simple", session_id="s1")
        state._runtime = runtime_with_mock_llm

        result = await graph.run(state, runtime=runtime_with_mock_llm)
        assert result.execution.status == "completed"
        assert result.node_outputs == {"only": "done"}

    @pytest.mark.asyncio
    async def test_run_with_conditional_edge_retry(self, runtime_with_mock_llm):
        """条件边 RETRY → 重试节点直到成功或超限。"""
        from haven.workflows.graph import WorkflowGraph
        from haven.workflows.state import WorkflowState
        from haven.workflows.edges import ConditionalEdge

        graph = WorkflowGraph(WorkflowState)

        call_count = [0]

        class CountingNode:
            name = "counter"

            async def __call__(self, state):
                call_count[0] += 1
                if call_count[0] < 3:
                    return {
                        "current_node": "counter",
                        "node_outputs": {**state.node_outputs, "counter": f"attempt {call_count[0]}"},
                        "errors": ["not ready"],
                    }
                return {
                    "current_node": "counter",
                    "node_outputs": {**state.node_outputs, "counter": "done"},
                    "status": "completed",
                }

        graph.add_node("counter", CountingNode())

        # Router: errors 非空 → RETRY, status=completed → END
        def need_retry(state):
            if state.status == "completed":
                return ConditionalEdge.END
            if state.errors:
                return ConditionalEdge.RETRY
            return ConditionalEdge.END

        graph.add_conditional_edge("counter", need_retry)
        graph.set_entry_point("counter")

        state = WorkflowState(task="count to done", session_id="s1")
        state._runtime = runtime_with_mock_llm

        result = await graph.run(state, runtime=runtime_with_mock_llm)
        assert call_count[0] == 3
        assert result.execution.status == "completed"

    @pytest.mark.asyncio
    async def test_run_max_retries_exceeded(self, runtime_with_mock_llm):
        """超过最大重试次数 → fail。"""
        from haven.workflows.graph import WorkflowGraph
        from haven.workflows.state import WorkflowState
        from haven.workflows.edges import ConditionalEdge

        graph = WorkflowGraph(WorkflowState)

        call_count = [0]

        class AlwaysFailsNode:
            name = "failing"

            async def __call__(self, state):
                call_count[0] += 1
                return {"errors": ["fail"], "status": "running"}

        graph.add_node("failing", AlwaysFailsNode())

        def always_retry(state):
            return ConditionalEdge.RETRY

        graph.add_conditional_edge("failing", always_retry)
        graph.set_entry_point("failing")

        state = WorkflowState(task="will fail", session_id="s1")
        state._runtime = runtime_with_mock_llm
        # 默认 max_retries=3
        state.execution.max_retries = 2

        result = await graph.run(state, runtime=runtime_with_mock_llm)
        assert result.execution.status == "failed"

    @pytest.mark.asyncio
    async def test_run_node_exception_caught(self, runtime_with_mock_llm):
        """节点抛异常 → errors 更新 + status=failed。"""
        from haven.workflows.graph import WorkflowGraph
        from haven.workflows.state import WorkflowState

        graph = WorkflowGraph(WorkflowState)

        class ExplodingNode:
            name = "boom"

            async def __call__(self, state):
                raise ValueError("BOOM!")

        graph.add_node("boom", ExplodingNode())
        graph.set_entry_point("boom")

        state = WorkflowState(task="crash", session_id="s1")
        state._runtime = runtime_with_mock_llm

        result = await graph.run(state, runtime=runtime_with_mock_llm)
        assert result.execution.status == "failed"
        assert any("BOOM" in e for e in result.errors)


class TestWorkflowGraphExecutionState:
    """ExecutionState 集成测试。"""

    def test_execution_initialized_in_state(self, workflow_state):
        """WorkflowState 创建时自动初始化 ExecutionState。"""
        es = workflow_state.execution
        assert es.status == "pending"
        assert es.task_id != ""
        assert len(es.task_id) == 12  # uuid hex[:12]

    def test_execution_lifecycle(self):
        from haven.runtime.execution import ExecutionState

        es = ExecutionState(task_id="test123", goal="测试任务")
        assert es.status == "pending"
        assert not es.is_terminal

        es.start()
        assert es.status == "running"
        assert es.is_running

        es.finish("完成")
        assert es.status == "completed"
        assert es.final_output == "完成"
        assert es.is_terminal

    def test_execution_fail(self):
        from haven.runtime.execution import ExecutionState

        es = ExecutionState(task_id="t1")
        es.start()
        es.fail("出错了")
        assert es.status == "failed"
        assert "出错了" in es.errors
        assert es.is_terminal
        assert es.has_errors

    def test_execution_pause_resume(self):
        from haven.runtime.execution import ExecutionState

        es = ExecutionState(task_id="t1")
        es.start()
        es.pause()
        assert es.status == "paused"
        assert not es.is_terminal

        es.resume()
        assert es.status == "running"

    def test_execution_snapshot_roundtrip(self):
        from haven.runtime.execution import ExecutionState

        es = ExecutionState(task_id="t1", goal="测试")
        es.start()
        es.complete_step("step1", "output1")
        es.complete_step("step2", "output2")

        data = es.snapshot()
        restored = ExecutionState.from_snapshot(data)

        assert restored.task_id == es.task_id
        assert restored.goal == es.goal
        assert restored.completed_steps == es.completed_steps
        assert restored.step_outputs == es.step_outputs
        assert restored.status == es.status

    def test_execution_step_counting(self):
        from haven.runtime.execution import ExecutionState

        es = ExecutionState(task_id="t1")
        assert es.total_steps == 0

        es.start()
        es.current_step = "step1"
        # 1 current (not completed/failed yet)
        assert es.total_steps >= 1


# ============================================================================
# Helpers
# ============================================================================


class _AsyncMockNode:
    """Mock 节点 — 返回固定 output 和 state updates。"""

    def __init__(self, name: str, output: str):
        self.name = name
        self._output = output

    async def __call__(self, state):
        return {
            "current_node": self.name,
            "node_outputs": {**state.node_outputs, self.name: self._output},
        }
