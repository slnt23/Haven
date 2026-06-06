"""AgentRuntime — V3 执行引擎，基于 LangGraph create_react_agent + 中间件管道。

职责：
  1. LLM     — 模型初始化、切换
  2. Tool    — 工具注册/激活/解析
  3. Memory  — LangGraph SqliteSaver 自动持久化 + pre_model_hook 消息裁剪
  4. State   — 会话状态
  5. Context — 委托 MiddlewarePipeline 组装上下文
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from typing import Any, AsyncIterator

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.messages.utils import count_tokens_approximately, trim_messages
from langchain_core.tools import BaseTool
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph.state import CompiledStateGraph
from langgraph.prebuilt import create_react_agent

from haven.config import get_auxiliary_model, settings
from haven.core.llm import create_llm
from haven.core.state import RuntimeState

logger = logging.getLogger("haven.runtime")


class AgentRuntime:
    """V3 执行引擎。使用中间件管道组装上下文，LangGraph create_react_agent 执行。

    中间件通过 ``_pipeline.before(state)`` 自动注入 system prompt、
    技能 prompt、记忆上下文、项目文件等。
    """

    def __init__(self, name: str = "runtime"):
        self.name = name

        self.llm: BaseChatModel | None = None
        self.aux_llm: BaseChatModel | None = None
        self._tools: dict[str, BaseTool] = {}
        self._active_tools: list[BaseTool] = []
        self.state = RuntimeState()

        self._agent: CompiledStateGraph | None = None
        self._agent_tools_hash: int = 0
        self._pipeline: Any = None

        db_dir = Path.cwd() / ".data"
        db_dir.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(db_dir / "checkpoint.db"), check_same_thread=False)
        self._checkpointer = SqliteSaver(conn)
        self._checkpointer.setup()

        self.max_iterations = settings.agent_max_iterations

    # ==================================================================
    # LLM
    # ==================================================================

    def init_llm(self, model_name: str | None = None) -> BaseChatModel:
        if self.llm is not None:
            return self.llm
        self.llm = create_llm(model_name)
        self.aux_llm = create_llm(get_auxiliary_model())
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
    # LangGraph Agent
    # ==================================================================

    @staticmethod
    def _pre_model_hook(state: dict, config: dict) -> dict:
        """在 LLM 调用前裁剪消息 + 注入 system_prompt。"""
        sp = config.get("configurable", {}).get("system_prompt", "")
        msgs = list(state.get("messages", []))
        if sp:
            msgs = [SystemMessage(content=sp)] + msgs
        trimmed = trim_messages(
            msgs,
            max_tokens=settings.context_window_tokens or 8000,
            strategy="last",
            token_counter=count_tokens_approximately,
            include_system=True,
            start_on="human",
        )
        return {"llm_input_messages": trimmed}

    def _get_agent(self, tools: list[BaseTool]) -> CompiledStateGraph:
        tools_hash = hash(tuple(id(t) for t in tools))
        if self._agent is not None and self._agent_tools_hash == tools_hash:
            return self._agent

        if self.llm is None:
            self.init_llm()

        self._agent = create_react_agent(
            model=self.llm,
            tools=tools,
            checkpointer=self._checkpointer,
            pre_model_hook=self._pre_model_hook,
        )
        self._agent_tools_hash = tools_hash
        return self._agent

    def _build_config(self, system_prompt: str = "") -> dict:
        return {
            "configurable": {
                "thread_id": self.state.session_id,
                "system_prompt": system_prompt,
            },
            "recursion_limit": self.max_iterations * 2 + 10,
        }

    # ==================================================================
    # Execution
    # ==================================================================

    async def run(
        self,
        task: str,
        *,
        active_skills: list[Any] | None = None,
        active_tools: list[BaseTool] | None = None,
        **kwargs: Any,
    ) -> str:
        if self.llm is None:
            self.init_llm()

        tools = active_tools or self._active_tools
        agent = self._get_agent(tools)

        # 中间件管道组装上下文
        skill_names = [getattr(s, "name", str(s)) for s in (active_skills or [])]
        state: dict[str, Any] = {
            "task": task,
            "messages": [HumanMessage(content=task)],
            "system_prompt": "",
            "active_skills": skill_names,
        }
        if self._pipeline is not None:
            state = await self._pipeline.before(state)

        sp = state.get("system_prompt", "")
        config = self._build_config(system_prompt=sp)

        result = await agent.ainvoke(
            {"messages": [HumanMessage(content=task)]},
            config=config,
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
        active_skills: list[Any] | None = None,
        active_tools: list[BaseTool] | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        if self.llm is None:
            self.init_llm()

        tools = active_tools or self._active_tools
        agent = self._get_agent(tools)

        skill_names = [getattr(s, "name", str(s)) for s in (active_skills or [])]
        state: dict[str, Any] = {
            "task": task,
            "messages": [HumanMessage(content=task)],
            "system_prompt": "",
            "active_skills": skill_names,
        }
        if self._pipeline is not None:
            state = await self._pipeline.before(state)

        sp = state.get("system_prompt", "")
        config = self._build_config(system_prompt=sp)

        async for event in agent.astream_events(
            {"messages": [HumanMessage(content=task)]},
            config=config,
            version="v2",
        ):
            kind = event.get("event", "")
            if kind == "on_chat_model_stream":
                chunk = event.get("data", {}).get("chunk")
                if chunk and hasattr(chunk, "content") and chunk.content:
                    yield chunk.content

        self.state.turn_count += 1

    # ==================================================================
    # Lifecycle
    # ==================================================================

    def reset(self) -> None:
        self.state.reset_turn()
