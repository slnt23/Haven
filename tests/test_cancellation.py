"""ExecutionContext — 任务取消机制测试。"""

from __future__ import annotations

from unittest.mock import AsyncMock

from langchain_core.messages import AIMessage
import pytest


class TestExecutionContext:
    """ExecutionContext 核心测试。"""

    def test_default_state(self):
        from haven.runtime.execution import ExecutionContext

        ctx = ExecutionContext()
        assert ctx.cancelled is False
        assert ctx.task_id != ""
        assert len(ctx.task_id) == 12

    def test_cancel_sets_flag(self):
        from haven.runtime.execution import ExecutionContext

        ctx = ExecutionContext(task_id="test123")
        ctx.cancel()
        assert ctx.cancelled is True

    def test_cancel_idempotent(self):
        from haven.runtime.execution import ExecutionContext

        ctx = ExecutionContext()
        ctx.cancel()
        ctx.cancel()
        assert ctx.cancelled is True

    def test_started_at_recorded(self):
        from haven.runtime.execution import ExecutionContext

        ctx = ExecutionContext()
        assert ctx.started_at > 0


class TestRuntimeCancellation:
    """AgentRuntime 取消测试。"""

    @pytest.fixture
    def rt(self, runtime_with_mock_llm):
        from langchain_core.tools import BaseTool

        rt = runtime_with_mock_llm

        class EchoTool(BaseTool):
            name: str = "echo"
            description: str = "echo"

            def _run(self, text: str = "") -> str:
                return f"echo: {text}"

        rt.register_tool(EchoTool())
        rt._active_tools = [rt._tools["echo"]]
        rt.bind_tools_to_llm()
        return rt

    @pytest.mark.asyncio
    async def test_cancel_before_tool_loop(self, rt):
        """取消后首次迭代即终止。"""
        from haven.runtime.execution import ExecutionContext

        ctx = ExecutionContext(task_id="t1")
        ctx.cancel()
        rt.set_context(ctx)

        # mock LLM 返回 tool_calls 以便进入 while 循环
        call_count = [0]

        async def _mock_ainvoke(messages, **kwargs):
            call_count[0] += 1
            msg = AIMessage(content="")
            msg.tool_calls = [{"name": "echo", "args": {"text": "hello"}, "id": "call_1"}]
            return msg

        rt.llm.ainvoke = AsyncMock(side_effect=_mock_ainvoke)

        result = await rt.run("echo hello", use_memory=False)
        assert "[已取消]" in result
        # 取消检查在 while 循环开头——LLM 尚未调用即终止
        assert call_count[0] == 0

    @pytest.mark.asyncio
    async def test_cancel_during_tool_loop(self, rt):
        """工具循环中取消——下次迭代时终止。"""
        from haven.runtime.execution import ExecutionContext

        ctx = ExecutionContext(task_id="t2")
        rt.set_context(ctx)

        call_count = [0]

        async def _mock_ainvoke(messages, **kwargs):
            call_count[0] += 1
            if call_count[0] == 2:
                # 第二轮时触发取消
                ctx.cancel()
            msg = AIMessage(content="")
            msg.tool_calls = [
                {
                    "name": "echo",
                    "args": {"text": str(call_count[0])},
                    "id": f"call_{call_count[0]}",
                }
            ]
            return msg

        rt.llm.ainvoke = AsyncMock(side_effect=_mock_ainvoke)

        result = await rt.run("loop test", use_memory=False)
        assert "[已取消]" in result
        assert call_count[0] == 2

    @pytest.mark.asyncio
    async def test_no_context_no_cancel(self, rt):
        """未注入 ExecutionContext 时不触发取消。"""
        rt.llm.ainvoke = AsyncMock(return_value=AIMessage(content="正常响应"))

        result = await rt.run("hello", use_memory=False)
        assert result == "正常响应"


class TestWorkflowCancellation:
    """WorkflowGraph 取消测试。"""

    @pytest.mark.asyncio
    async def test_cancel_before_node_execution(self, runtime_with_mock_llm):
        """节点执行前取消——Workflow 终止。"""
        from haven.runtime.execution import ExecutionContext
        from haven.workflows.graph import WorkflowGraph
        from haven.workflows.state import WorkflowState

        graph = WorkflowGraph(WorkflowState)

        executed = [False]

        class CountingNode:
            name = "step1"

            async def __call__(self, state):
                executed[0] = True
                return {
                    "current_node": "step1",
                    "node_outputs": {**state.node_outputs, "step1": "done"},
                }

        graph.add_node("step1", CountingNode())
        graph.set_entry_point("step1")

        ctx = ExecutionContext(task_id="wf1")
        ctx.cancel()
        graph.set_context(ctx)

        state = WorkflowState(task="test", session_id="s1")
        state._runtime = runtime_with_mock_llm

        result = await graph.run(state, runtime=runtime_with_mock_llm)
        assert result.execution.status == "cancelled"
        assert executed[0] is False  # 节点未被调用

    @pytest.mark.asyncio
    async def test_cancel_during_multi_node(self, runtime_with_mock_llm):
        """多节点工作流中第二个节点前取消。"""
        from haven.runtime.execution import ExecutionContext
        from haven.workflows.graph import WorkflowGraph
        from haven.workflows.state import WorkflowState

        graph = WorkflowGraph(WorkflowState)

        execution_order: list[str] = []

        class Node1:
            name = "node1"

            async def __call__(self, state):
                execution_order.append("node1")
                return {
                    "current_node": "node1",
                    "node_outputs": {**state.node_outputs, "node1": "ok"},
                }

        class Node2:
            name = "node2"

            async def __call__(self, state):
                execution_order.append("node2")
                return {
                    "current_node": "node2",
                    "node_outputs": {**state.node_outputs, "node2": "ok"},
                }

        graph.add_node("node1", Node1())
        graph.add_node("node2", Node2())
        graph.add_edge("node1", "node2")
        graph.set_entry_point("node1")

        ctx = ExecutionContext(task_id="wf2")
        graph.set_context(ctx)

        # 在 node1 执行后取消
        async def _cancel_after_node1():
            original_run = graph.run

            async def _wrapped(state, **kwargs):
                # 先执行 node1
                if runtime_with_mock_llm is not None:
                    state._runtime = runtime_with_mock_llm
                await graph._nodes["node1"](state)
                # 取消
                ctx.cancel()
                # 继续原始执行——但下一个 while 迭代会检测到取消
                return await original_run(state, **kwargs)

            return await _wrapped(
                WorkflowState(task="test", session_id="s1"), runtime=runtime_with_mock_llm
            )

        # 更简单的方式：直接执行图，但在 node1 执行期间取消
        state = WorkflowState(task="test", session_id="s1")
        state._runtime = runtime_with_mock_llm

        # node1 执行后取消
        await graph._nodes["node1"](state)
        ctx.cancel()

        result = await graph.run(state, runtime=runtime_with_mock_llm)
        assert result.execution.status == "cancelled"

    @pytest.mark.asyncio
    async def test_no_context_workflow_normal(self, runtime_with_mock_llm):
        """未注入 ExecutionContext 时工作流正常执行。"""
        from haven.workflows.graph import WorkflowGraph
        from haven.workflows.state import WorkflowState

        graph = WorkflowGraph(WorkflowState)

        class OKNode:
            name = "ok"

            async def __call__(self, state):
                return {"current_node": "ok", "node_outputs": {**state.node_outputs, "ok": "done"}}

        graph.add_node("ok", OKNode())
        graph.set_entry_point("ok")

        state = WorkflowState(task="test", session_id="s1")
        state._runtime = runtime_with_mock_llm

        result = await graph.run(state, runtime=runtime_with_mock_llm)
        assert result.execution.status == "completed"


class TestToolExecutionCancellation:
    """工具执行期间取消测试。"""

    @pytest.mark.asyncio
    async def test_cancel_during_tool_execution(self, runtime_with_mock_llm):
        """工具执行过程中触发取消——下次循环检测到。"""
        from langchain_core.tools import BaseTool

        from haven.runtime.execution import ExecutionContext

        ctx = ExecutionContext(task_id="t3")
        rt = runtime_with_mock_llm

        tool_call_count = [0]

        class SlowTool(BaseTool):
            name: str = "slow_tool"
            description: str = "慢工具"

            def _run(self, **kwargs):
                tool_call_count[0] += 1
                # 第二次工具调用后取消
                if tool_call_count[0] == 2:
                    ctx.cancel()
                return f"result_{tool_call_count[0]}"

            async def _arun(self, **kwargs):
                return self._run(**kwargs)

        rt.register_tool(SlowTool())
        rt._active_tools = [rt._tools["slow_tool"]]
        rt.bind_tools_to_llm()
        rt.set_context(ctx)

        call_count = [0]

        async def _mock_ainvoke(messages, **kwargs):
            call_count[0] += 1
            msg = AIMessage(content="")
            msg.tool_calls = [
                {
                    "name": "slow_tool",
                    "args": {"input": str(call_count[0])},
                    "id": f"call_{call_count[0]}",
                }
            ]
            return msg

        rt.llm.ainvoke = AsyncMock(side_effect=_mock_ainvoke)

        result = await rt.run("do work", use_memory=False)
        assert "[已取消]" in result
        assert tool_call_count[0] == 2


class TestExecutionStateCancelled:
    """ExecutionState cancelled 状态测试。"""

    def test_status_cancelled(self):
        from haven.runtime.execution import ExecutionState

        es = ExecutionState(task_id="t1")
        es.start()
        es.status = "cancelled"

        # cancelled 是终态
        assert es.status == "cancelled"

    def test_snapshot_includes_cancelled(self):
        from haven.runtime.execution import ExecutionState

        es = ExecutionState(task_id="t1")
        es.start()
        es.status = "cancelled"

        data = es.snapshot()
        assert data["status"] == "cancelled"

        restored = ExecutionState.from_snapshot(data)
        assert restored.status == "cancelled"


class TestAgentRuntimeCancelledProperty:
    """AgentRuntime.cancelled 属性测试。"""

    def test_cancelled_false_without_context(self, runtime_with_mock_llm):
        assert runtime_with_mock_llm.cancelled is False

    def test_cancelled_false_with_context_not_cancelled(self, runtime_with_mock_llm):
        from haven.runtime.execution import ExecutionContext

        ctx = ExecutionContext()
        runtime_with_mock_llm.set_context(ctx)
        assert runtime_with_mock_llm.cancelled is False

    def test_cancelled_true_after_cancel(self, runtime_with_mock_llm):
        from haven.runtime.execution import ExecutionContext

        ctx = ExecutionContext()
        runtime_with_mock_llm.set_context(ctx)
        ctx.cancel()
        assert runtime_with_mock_llm.cancelled is True
