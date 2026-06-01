"""AgentRuntime — V3 执行引擎，基于 LangGraph create_react_agent + 中间件管道。

职责：
  1. LLM     — 模型初始化、切换
  2. Tool    — 工具注册/激活/解析
  3. Memory  — 短期消息窗口 + 长期事实存储
  4. State   — 会话状态
  5. Context — 委托 MiddlewarePipeline 组装上下文
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, AsyncIterator

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from langchain_core.tools import BaseTool
from langgraph.graph.state import CompiledStateGraph
from langgraph.prebuilt import create_react_agent

from haven.config import settings
from haven.core.llm import create_llm
from haven.core.state import RuntimeState
from haven.memory.manager import MemoryManager

logger = logging.getLogger("haven.runtime")


class AgentRuntime:
    """V3 执行引擎。使用中间件管道组装上下文，LangGraph create_react_agent 执行。

    中间件通过 ``_pipeline.before(state)`` 自动注入 system prompt、
    技能 prompt、记忆上下文、项目文件等。
    """

    def __init__(self, name: str = "runtime"):
        self.name = name

        self.llm: BaseChatModel | None = None
        self._tools: dict[str, BaseTool] = {}
        self._active_tools: list[BaseTool] = []
        self.memory = MemoryManager()
        self.state = RuntimeState()

        self._agent: CompiledStateGraph | None = None
        self._agent_tools_hash: int = 0
        self._pipeline: Any = None

        self.max_iterations = settings.agent_max_iterations

    # ==================================================================
    # LLM
    # ==================================================================

    def init_llm(self, model_name: str | None = None) -> BaseChatModel:
        if self.llm is not None:
            return self.llm
        self.llm = create_llm(model_name)
        return self.llm

    def switch_model(self, model_name: str) -> str:
        self.llm = create_llm(model_name)
        self._agent = None
        return getattr(self.llm, "model_name", model_name)

    # ==================================================================
    # Tool
    # ==================================================================

    def register_tool(self, tool: BaseTool) -> None:
        self._tools[tool.name] = tool
        self._agent = None

    def register_tools(self, tools: dict[str, BaseTool]) -> None:
        for name, tool in tools.items():
            self._tools[name] = tool
        self._agent = None

    def activate_tools(self, names: list[str]) -> None:
        self._active_tools = [self._tools[n] for n in names if n in self._tools]
        self._agent = None

    def activate_all_tools(self) -> None:
        self._active_tools = list(self._tools.values())
        self._agent = None

    def get_tool(self, name: str) -> BaseTool | None:
        return self._tools.get(name)

    def resolve_tools(
        self, skill_names: list[str], *, permissions: list[str] | None = None,
    ) -> list[BaseTool]:
        if not hasattr(self, "_tool_resolver") or self._tool_resolver is None:
            return self._active_tools

        result = self._tool_resolver.resolve(
            skill_names,
            channel=getattr(self.state, "channel", "cli"),
            permissions=permissions,
        )
        if result.warnings:
            for w in result.warnings:
                logger.warning("ToolResolver: %s", w)

        self._active_tools = list(result.tools)
        self._agent = None
        return self._active_tools

    # ==================================================================
    # Messages
    # ==================================================================

    def build_messages(
        self, task: str, *, history: list[BaseMessage] | None = None,
    ) -> list[BaseMessage]:
        messages: list[BaseMessage] = []
        for msg in history or self.memory.working.get_messages():
            messages.append(msg)
        messages.append(HumanMessage(content=task))
        return messages

    # ==================================================================
    # LangGraph Agent
    # ==================================================================

    def _get_agent(self, tools: list[BaseTool]) -> CompiledStateGraph:
        tools_hash = hash(tuple(id(t) for t in tools))
        if self._agent is not None and self._agent_tools_hash == tools_hash:
            return self._agent

        if self.llm is None:
            self.init_llm()

        self._agent = create_react_agent(model=self.llm, tools=tools)
        self._agent_tools_hash = tools_hash
        return self._agent

    # ==================================================================
    # Execution
    # ==================================================================

    async def run(
        self,
        task: str,
        *,
        history: list[BaseMessage] | None = None,
        active_skills: list[Any] | None = None,
        active_tools: list[BaseTool] | None = None,
        **kwargs: Any,
    ) -> str:
        if self.llm is None:
            self.init_llm()

        tools = active_tools or self._active_tools
        agent = self._get_agent(tools)

        messages = self.build_messages(task, history=history)

        # 中间件管道组装上下文
        skill_names = [getattr(s, "name", str(s)) for s in (active_skills or [])]
        state: dict[str, Any] = {
            "task": task,
            "messages": messages,
            "system_prompt": "",
            "active_skills": skill_names,
        }
        if self._pipeline is not None:
            state = await self._pipeline.before(state)

        # 将 system_prompt 注入到消息列
        final_messages = list(state["messages"])
        sp = state.get("system_prompt", "")
        if sp:
            final_messages.insert(0, SystemMessage(content=sp))

        result = await agent.ainvoke(
            {"messages": final_messages},
            config={"recursion_limit": self.max_iterations * 2 + 10},
        )
        output = result["messages"][-1]
        output_text = output.content if hasattr(output, "content") else str(output)

        self.state.turn_count += 1
        return output_text

    # ==================================================================
    # Streaming
    # ==================================================================

    async def astream(
        self,
        task: str,
        *,
        history: list[BaseMessage] | None = None,
        active_skills: list[Any] | None = None,
        active_tools: list[BaseTool] | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        if self.llm is None:
            self.init_llm()

        tools = active_tools or self._active_tools
        agent = self._get_agent(tools)

        messages = self.build_messages(task, history=history)

        skill_names = [getattr(s, "name", str(s)) for s in (active_skills or [])]
        state: dict[str, Any] = {
            "task": task,
            "messages": messages,
            "system_prompt": "",
            "active_skills": skill_names,
        }
        if self._pipeline is not None:
            state = await self._pipeline.before(state)

        final_messages = list(state["messages"])
        sp = state.get("system_prompt", "")
        if sp:
            final_messages.insert(0, SystemMessage(content=sp))

        async for event in agent.astream_events(
            {"messages": final_messages},
            config={"recursion_limit": self.max_iterations * 2 + 10},
            version="v2",
        ):
            kind = event.get("event", "")
            if kind == "on_chat_model_stream":
                chunk = event.get("data", {}).get("chunk")
                if chunk and hasattr(chunk, "content") and chunk.content:
                    yield chunk.content

        self.state.turn_count += 1

    # ==================================================================
    # Memory
    # ==================================================================

    def save_turn(self, user_input: str, response: str) -> None:
        asyncio.create_task(self.memory.record_turn(user_input, response))

    async def extract_facts_async(self) -> None:
        if self.llm is None:
            return
        self.memory.set_llm(self.llm)
        msgs = self.memory.working.get_messages()
        user_msg, assistant_msg = "", ""
        for m in msgs:
            role = getattr(m, "type", "")
            content = getattr(m, "content", "")
            if role == "human":
                user_msg = content
            elif role == "ai":
                assistant_msg = content
        if user_msg or assistant_msg:
            await self.memory._extract_facts(user_msg, assistant_msg)

    def reset(self) -> None:
        asyncio.create_task(self.memory.working.clear())
        self.state.reset_turn()
