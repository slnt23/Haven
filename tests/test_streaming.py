"""AgentRuntime.astream() + PlannerAgent.execute_stream() 测试。"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

# ============================================================================
# Mock helpers
# ============================================================================


class FakeChunk:
    """模拟 AIMessageChunk。"""

    def __init__(self, content: str = ""):
        self.content = content

    def __add__(self, other: "FakeChunk") -> "FakeChunk":
        return FakeChunk(self.content + other.content)


async def _token_stream(text: str):
    """将文本拆分为单字 token 流。"""
    for ch in text:
        yield FakeChunk(content=ch)


class TestAgentRuntimeAstream:
    """AgentRuntime.astream() 核心测试。"""

    @pytest.fixture
    def rt(self, runtime_with_mock_llm):
        rt = runtime_with_mock_llm
        rt._active_tools = []
        return rt

    @pytest.mark.asyncio
    async def test_astream_chunks_in_order(self, rt):
        """逐 token 输出，顺序正确。"""
        rt.llm.astream = MagicMock(return_value=_token_stream("你好世界"))

        chunks: list[str] = []
        async for chunk in rt.astream("hello", use_memory=False):
            chunks.append(chunk)

        assert chunks == ["你", "好", "世", "界"]

    @pytest.mark.asyncio
    async def test_astream_final_result_complete(self, rt):
        """累积所有 chunk 得到完整结果。"""
        text = "这是一个完整的长文本响应用于测试流式输出"
        rt.llm.astream = MagicMock(return_value=_token_stream(text))

        collected: list[str] = []
        async for chunk in rt.astream("test", use_memory=False):
            collected.append(chunk)

        assert "".join(collected) == text

    @pytest.mark.asyncio
    async def test_astream_empty_response(self, rt):
        """空响应不 yield 任何 token。"""
        rt.llm.astream = MagicMock(return_value=_token_stream(""))

        chunks: list[str] = []
        async for chunk in rt.astream("test", use_memory=False):
            chunks.append(chunk)

        assert chunks == []

    @pytest.mark.asyncio
    async def test_astream_skips_empty_chunks(self, rt):
        """空 content 的 chunk 被跳过。"""

        async def mixed_stream():
            yield FakeChunk(content="A")
            yield FakeChunk(content="")
            yield FakeChunk(content="B")

        rt.llm.astream = MagicMock(return_value=mixed_stream())

        chunks: list[str] = []
        async for chunk in rt.astream("test", use_memory=False):
            chunks.append(chunk)

        assert chunks == ["A", "B"]

    @pytest.mark.asyncio
    async def test_astream_with_system_prompt(self, rt):
        """传入 system_prompt 时正确注入。"""
        rt.llm.astream = MagicMock(return_value=_token_stream("ok"))

        async for _chunk in rt.astream("test", system_prompt="你是一个助手", use_memory=False):
            pass

        # 验证 messages 包含 SystemMessage
        call_args = rt.llm.astream.call_args[0][0]
        system_msgs = [m for m in call_args if m.type == "system"]
        assert len(system_msgs) == 1
        assert system_msgs[0].content == "你是一个助手"

    @pytest.mark.asyncio
    async def test_astream_initializes_llm(self):
        """llm 为 None 时自动初始化。"""
        from unittest.mock import patch

        from haven.runtime.runtime import AgentRuntime

        mock_llm = MagicMock()
        mock_llm.model_name = "mock"
        mock_llm.astream = MagicMock(return_value=_token_stream("hi"))
        mock_llm.bind_tools = MagicMock(return_value=mock_llm)

        with patch("haven.runtime.runtime.create_llm", return_value=mock_llm):
            rt = AgentRuntime(name="test")
            rt.context_manager.build = MagicMock(return_value=MagicMock(system_prompt=""))

            chunks: list[str] = []
            async for chunk in rt.astream("hello", use_memory=False):
                chunks.append(chunk)

        assert chunks == ["h", "i"]

    @pytest.mark.asyncio
    async def test_astream_with_tools_first_round(self, rt):
        """带工具时首轮流式输出文本。"""
        from langchain_core.messages import AIMessage

        call_count = [0]

        async def _stream_with_tool(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                yield FakeChunk(content="我来帮你")
            else:
                yield FakeChunk(content="完成")

        rt.llm.astream = MagicMock(side_effect=_stream_with_tool)
        rt.llm.ainvoke = AsyncMock(return_value=AIMessage(content="完成"))

        from langchain_core.tools import BaseTool

        class EchoTool(BaseTool):
            name: str = "echo"
            description: str = "echo"

            def _run(self, text: str = "") -> str:
                return f"echo: {text}"

        rt.register_tool(EchoTool())
        rt._active_tools = [rt._tools["echo"]]
        rt.bind_tools_to_llm()

        chunks: list[str] = []
        async for chunk in rt.astream("echo hello", use_memory=False):
            chunks.append(chunk)

        assert len(chunks) >= 1

    @pytest.mark.asyncio
    async def test_astream_hasattr_chunk(self, rt):
        """chunk 无 content 属性时 fallback 到 str()。"""

        class PlainChunk:
            def __str__(self):
                return "plain"

        async def plain_stream():
            yield PlainChunk()

        rt.llm.astream = MagicMock(return_value=plain_stream())

        chunks: list[str] = []
        async for chunk in rt.astream("test", use_memory=False):
            chunks.append(chunk)

        assert chunks == ["plain"]


class TestPlannerExecuteStream:
    """PlannerAgent.execute_stream() 测试。"""

    @pytest.fixture
    def planner(self, runtime_with_mock_llm, register_test_skills):
        from haven.runtime.planner import PlannerAgent

        # 设置 runtime.astream 返回简单流 — 必须用真实 async generator
        async def _mock_astream(*args, **kwargs):
            yield "流"
            yield "式"
            yield "响"
            yield "应"

        runtime_with_mock_llm.astream = _mock_astream

        p = PlannerAgent(runtime_with_mock_llm)
        return p

    @pytest.mark.asyncio
    async def test_execute_stream_simple(self, planner):
        """简单对话 → astream 直通。"""
        chunks: list[str] = []
        async for chunk in planner.execute_stream("你好"):
            chunks.append(chunk)

        assert "".join(chunks) == "流式响应"

    @pytest.mark.asyncio
    async def test_execute_stream_with_steps(self, planner):
        """多步任务 → 最后一步流式输出。"""
        from haven.runtime.planner import ExecutionPlan, PlanStep

        plan = ExecutionPlan(
            goal="两步任务",
            intent="development",
            complexity="medium",
            skills=["coder"],
            workflow=None,
            steps=[
                PlanStep(
                    order=1, description="步骤1", skill="coder", depends_on=[], expected_output=""
                ),
                PlanStep(
                    order=2, description="步骤2", skill="coder", depends_on=[1], expected_output=""
                ),
            ],
            reasoning="",
        )

        from unittest.mock import patch

        with patch.object(planner, "plan", new=AsyncMock(return_value=plan)):
            chunks: list[str] = []
            async for chunk in planner.execute_stream("多步任务"):
                chunks.append(chunk)

            assert len(chunks) == 4

    @pytest.mark.asyncio
    async def test_execute_stream_trivial(self, planner):
        """trivial 任务 → 快速路径仍然流式输出。"""
        chunks: list[str] = []
        async for chunk in planner.execute_stream("hi"):
            chunks.append(chunk)

        assert "".join(chunks) == "流式响应"


class TestRuntimeServiceStreamIntegration:
    """RuntimeService.chat_stream() 集成测试。"""

    @pytest.mark.asyncio
    async def test_chat_stream_uses_native_astream(self):
        """chat_stream 使用 PlannerAgent.execute_stream 原生流式。"""
        from unittest.mock import AsyncMock, MagicMock

        mock_planner = MagicMock()
        mock_runtime = MagicMock()
        mock_runtime.extract_facts_async = AsyncMock()

        async def _mock_execute_stream(task: str):
            yield "A"
            yield "B"
            yield "C"

        mock_planner.execute_stream = _mock_execute_stream

        svc = _create_service(mock_planner, mock_runtime)

        chunks: list[str] = []
        async for chunk in svc.chat_stream("test"):
            chunks.append(chunk)

        assert chunks == ["A", "B", "C"]

    @pytest.mark.asyncio
    async def test_chat_stream_not_initialized(self):
        """未初始化时返回错误。"""
        from haven.cli.services.runtime_service import RuntimeService

        svc = RuntimeService()
        chunks: list[str] = []
        async for chunk in svc.chat_stream("test"):
            chunks.append(chunk)

        assert "未初始化" in chunks[0]


def _create_service(mock_planner, mock_runtime):
    from haven.cli.services.runtime_service import RuntimeService

    svc = RuntimeService()
    svc._planner = mock_planner
    svc._runtime = mock_runtime
    svc._initialized = True
    return svc
