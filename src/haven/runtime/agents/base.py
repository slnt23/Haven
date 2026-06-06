"""BaseAgent — 专业 Agent 基类。

封装 LangGraph ReAct Agent 的执行逻辑。
每个实例是 tool 子集 + skill 子集 + system_prompt 扩展的组合。
"""

from __future__ import annotations

import logging
from typing import Any, AsyncIterator

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.messages.utils import count_tokens_approximately, trim_messages
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph.state import CompiledStateGraph
from langgraph.prebuilt import create_react_agent

from haven.config import settings
from haven.core.state import RuntimeState

logger = logging.getLogger("haven.agent")


class BaseAgent:
    """专业 Agent。封装 LangGraph ReAct Agent 的执行逻辑。"""

    def __init__(
        self,
        name: str,
        llm: BaseChatModel,
        tools: list[BaseTool],
        checkpointer: AsyncSqliteSaver,
        state: RuntimeState,
        *,
        agent_prompt: str = "",
        default_skills: list[str] | None = None,
        max_iterations: int | None = None,
    ):
        self.name = name
        self.llm = llm
        self._base_tools = list(tools)
        self._tools = list(tools)
        self._checkpointer = checkpointer
        self.state = state
        self.agent_prompt = agent_prompt
        self.default_skills = list(default_skills or [])
        self.max_iterations = max_iterations or settings.agent_max_iterations

        self._agent: CompiledStateGraph | None = None
        self._agent_tools_hash: int = 0

    # ==================================================================
    # LangGraph Agent
    # ==================================================================

    @staticmethod
    def _pre_model_hook(state: dict, config: RunnableConfig | None = None) -> dict:
        sp = state.get("system_prompt", "")
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

    def _get_agent(self) -> CompiledStateGraph:
        tools_hash = hash(tuple(id(t) for t in self._tools))
        if self._agent is not None and self._agent_tools_hash == tools_hash:
            return self._agent

        self._agent = create_react_agent(
            model=self.llm,
            tools=self._tools,
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
        system_prompt: str = "",
        **kwargs: Any,
    ) -> str:
        agent = self._get_agent()
        config = self._build_config(system_prompt=system_prompt)

        result = await agent.ainvoke(
            {"messages": [HumanMessage(content=task)], "system_prompt": system_prompt},
            config=config,
        )
        output = result["messages"][-1]
        output_text = output.content if hasattr(output, "content") else str(output)

        self.state.turn_count += 1
        return output_text

    async def astream(
        self,
        task: str,
        *,
        system_prompt: str = "",
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        agent = self._get_agent()
        config = self._build_config(system_prompt=system_prompt)

        async for event in agent.astream_events(
            {"messages": [HumanMessage(content=task)], "system_prompt": system_prompt},
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
    # 工具绑定
    # ==================================================================

    @property
    def base_tools(self) -> list[BaseTool]:
        return self._base_tools

    @property
    def tools(self) -> list[BaseTool]:
        return self._tools

    def set_tools(self, tools: list[BaseTool]) -> None:
        """动态切换当前轮次可用工具（变更后重建 LangGraph Agent）。"""
        self._tools = list(tools) if tools else list(self._base_tools)
        self._agent = None

    def restore_base_tools(self) -> None:
        """恢复为 app.yaml 声明的静态工具上限。"""
        self._tools = list(self._base_tools)
        self._agent = None

    # ==================================================================
    # Lifecycle
    # ==================================================================

    def reset(self) -> None:
        self.state.reset_turn()
