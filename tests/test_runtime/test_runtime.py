"""AgentRuntime.run() 测试 — 核心执行引擎。"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestAgentRuntimeInit:
    """AgentRuntime 初始化测试。"""

    def test_default_init(self):
        from haven.runtime.runtime import AgentRuntime
        rt = AgentRuntime(name="test")
        assert rt.name == "test"
        assert rt.llm is None
        assert rt._tools == {}
        assert rt._active_tools == []
        assert rt.memory is not None
        assert rt.state is not None
        assert rt.prompt_builder is not None
        assert rt.context_manager is not None

    def test_init_llm_creates_model(self):
        from unittest.mock import patch
        from haven.runtime.runtime import AgentRuntime

        mock_llm_obj = MagicMock()
        mock_llm_obj.model_name = "mock-model"
        mock_llm_obj.bind_tools = MagicMock(return_value=mock_llm_obj)

        # 必须 patch runtime 模块中已导入的 create_llm 引用
        with patch("haven.runtime.runtime.create_llm", return_value=mock_llm_obj):
            rt = AgentRuntime(name="test")
            result = rt.init_llm()

        assert result is mock_llm_obj
        assert rt.llm is mock_llm_obj

    def test_init_llm_returns_existing(self, runtime_with_mock_llm):
        rt = runtime_with_mock_llm
        result = rt.init_llm()
        assert result is rt.llm


class TestAgentRuntimeRun:
    """AgentRuntime.run() — 执行路径测试。"""

    @pytest.mark.asyncio
    async def test_run_direct_no_tools(self, runtime_with_mock_llm):
        """无工具 → _invoke_direct 直通。"""
        rt = runtime_with_mock_llm
        rt._active_tools = []

        result = await rt.run("你好", use_memory=False)
        assert result == "mock response"
        rt.llm.ainvoke.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_run_initializes_llm_if_none(self):
        """llm 为 None 时自动 init。"""
        from haven.runtime.runtime import AgentRuntime

        mock_llm_obj = MagicMock()
        mock_llm_obj.model_name = "mock-model"
        mock_llm_obj.ainvoke = AsyncMock(return_value=MagicMock(content="auto init"))
        mock_llm_obj.bind_tools = MagicMock(return_value=mock_llm_obj)

        with patch("haven.runtime.runtime.create_llm", return_value=mock_llm_obj):
            rt = AgentRuntime(name="test")
            rt.context_manager.build = MagicMock(return_value=MagicMock(system_prompt=""))
            result = await rt.run("hello", use_memory=False)

        assert result == "auto init"

    @pytest.mark.asyncio
    async def test_run_with_system_prompt(self, runtime_with_mock_llm):
        """传入预生成 system_prompt 时跳过 build_system_prompt。"""
        rt = runtime_with_mock_llm
        rt._active_tools = []

        result = await rt.run(
            "test",
            system_prompt="你是一个测试助手",
            use_memory=False,
        )
        assert result == "mock response"

        call_args = rt.llm.ainvoke.call_args[0][0]
        system_msgs = [m for m in call_args if m.type == "system"]
        assert len(system_msgs) == 1
        assert system_msgs[0].content == "你是一个测试助手"

    @pytest.mark.asyncio
    async def test_run_passes_active_skills_to_context(self, runtime_with_mock_llm):
        """active_skills 传入时，default skill 作为 personality，非 default 作为 domain。"""
        rt = runtime_with_mock_llm
        rt._active_tools = []

        from haven.skills.base_skill import BaseSkill
        domain_skill = BaseSkill(
            name="coder",
            description="代码",
            prompt="写代码的 skill",
            default=False,
        )

        with patch.object(rt.context_manager, "build") as mock_build:
            mock_bundle = MagicMock()
            mock_bundle.system_prompt = "mock prompt"
            mock_build.return_value = mock_bundle

            await rt.run("写排序", active_skills=[domain_skill], use_memory=False)

            call_kwargs = mock_build.call_args.kwargs
            assert call_kwargs["domain_skills"] == [domain_skill]

    @pytest.mark.asyncio
    async def test_run_with_tool_loop(self, runtime_with_mock_llm):
        """带工具调用循环 — 第一次返回 tool_calls，第二次返回文本。"""
        rt = runtime_with_mock_llm

        from langchain_core.messages import AIMessage

        call_count = [0]

        async def _mock_ainvoke(messages, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                msg = AIMessage(content="")
                msg.tool_calls = [{"name": "echo", "args": {"text": "hello"}, "id": "call_1"}]
                return msg
            else:
                return AIMessage(content="tool result processed")

        rt.llm.ainvoke = AsyncMock(side_effect=_mock_ainvoke)

        from langchain_core.tools import BaseTool

        class EchoTool(BaseTool):
            name: str = "echo"
            description: str = "回显输入"

            def _run(self, text: str = "") -> str:
                return f"echo: {text}"

            async def _arun(self, text: str = "") -> str:
                return f"echo: {text}"

        rt.register_tool(EchoTool())
        rt._active_tools = [rt._tools["echo"]]
        rt.bind_tools_to_llm()

        result = await rt.run("echo hello", use_memory=False)
        assert result == "tool result processed"
        assert call_count[0] == 2

    @pytest.mark.asyncio
    async def test_run_with_history(self, runtime_with_mock_llm):
        """传入 history 参数覆盖 memory 历史。"""
        rt = runtime_with_mock_llm
        rt._active_tools = []

        from langchain_core.messages import HumanMessage, AIMessage
        history = [
            HumanMessage(content="之前的问题"),
            AIMessage(content="之前的回答"),
        ]

        await rt.run("新问题", history=history, use_memory=False)

        call_args = rt.llm.ainvoke.call_args[0][0]
        msgs = [m for m in call_args if m.type in ("human", "ai")]
        assert len(msgs) == 3  # 2 history + 1 new human


class TestAgentRuntimeTools:
    """工具注册与绑定测试。"""

    def _make_tool(self, tool_name: str):
        from langchain_core.tools import BaseTool

        class _T(BaseTool):
            name: str = tool_name
            description: str = "测试工具"

            def _run(self, **kwargs):
                return "ok"

            async def _arun(self, **kwargs):
                return "ok"

        return _T()

    def test_register_tool(self, runtime_with_mock_llm):
        rt = runtime_with_mock_llm
        rt.register_tool(self._make_tool("my_tool"))
        assert "my_tool" in rt._tools

    def test_get_tool(self, runtime_with_mock_llm):
        rt = runtime_with_mock_llm
        rt.register_tool(self._make_tool("my_tool"))
        t = rt.get_tool("my_tool")
        assert t is not None
        assert rt.get_tool("nope") is None

    def test_activate_tools_subset(self, runtime_with_mock_llm):
        rt = runtime_with_mock_llm
        rt.register_tool(self._make_tool("tool_a"))
        rt.register_tool(self._make_tool("tool_b"))
        rt.activate_tools(["tool_a"])
        assert len(rt._active_tools) == 1
        assert rt._active_tools[0].name == "tool_a"

    def test_activate_all_tools(self, runtime_with_mock_llm):
        rt = runtime_with_mock_llm
        rt.register_tool(self._make_tool("tool_a"))
        rt.register_tool(self._make_tool("tool_b"))
        rt.activate_all_tools()
        assert len(rt._active_tools) == 2

    def test_activate_nonexistent_skipped(self, runtime_with_mock_llm):
        rt = runtime_with_mock_llm
        rt.register_tool(self._make_tool("tool_a"))
        rt.activate_tools(["tool_a", "ghost"])
        assert len(rt._active_tools) == 1

    def test_switch_model_rebinds_tools(self, runtime_with_mock_llm):
        from unittest.mock import MagicMock, patch

        rt = runtime_with_mock_llm
        rt.register_tool(self._make_tool("my_tool"))
        rt.activate_all_tools()

        new_llm = MagicMock()
        new_llm.model_name = "new-model"
        new_llm.bind_tools = MagicMock(return_value=new_llm)

        with patch("haven.runtime.runtime.create_llm", return_value=new_llm):
            rt.switch_model("deepseek-v4-pro")

        new_llm.bind_tools.assert_called_once()


class TestAgentRuntimeMemory:
    """Memory 便捷方法测试。"""

    def test_add_message_and_history(self, runtime_with_mock_llm):
        from langchain_core.messages import HumanMessage
        rt = runtime_with_mock_llm
        rt.memory.add_message(HumanMessage(content="你好"))
        assert len(rt.memory) == 1
        assert rt.memory.get_history()[0].content == "你好"

    def test_reset(self, runtime_with_mock_llm):
        from langchain_core.messages import HumanMessage
        rt = runtime_with_mock_llm
        rt.memory.add_message(HumanMessage(content="hello"))
        assert len(rt.memory) == 1
        rt.reset()
        assert len(rt.memory) == 0

    def test_save_turn_uses_working_memory(self, runtime_with_mock_llm):
        """Runtime 的 memory 支持 add_message 和 get_history。"""
        from langchain_core.messages import HumanMessage, AIMessage
        rt = runtime_with_mock_llm
        rt.memory.add_message(HumanMessage(content="你好"))
        rt.memory.add_message(AIMessage(content="你好！"))
        history = rt.memory.get_history()
        assert len(history) == 2
        assert history[0].content == "你好"
        assert history[1].content == "你好！"
