"""BaseAgent —— 专业 Agent 基类，封装 LangGraph ReAct Agent。

每个 Agent 实例 = LangChain 工具集 + system_prompt。
工具在创建时一次性绑定，LLM 通过 Function Calling 自行决定调用哪个。

System_prompt 直接作为 SystemMessage 放到 messages 列表最前面 ——
不依赖 LangGraph 版本的 prompt 参数行为差异。
"""

from __future__ import annotations

import logging
from typing import Any, AsyncIterator

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import BaseTool
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph.state import CompiledStateGraph
from langgraph.prebuilt import create_react_agent

from haven.config import settings
from haven.core.state import RuntimeState

logger = logging.getLogger("haven.agent")


class BaseAgent:
    """LangGraph ReAct Agent 的轻量包装。

    职责：
      - 持有 LLM + 工具 + checkpointer
      - system_prompt 以 SystemMessage 形式注入 messages
      - 提供 run() / astream() 两种执行模式

    不负责：
      - Tool 选择（LLM Function Calling）
      - Context 构建（ContextBuilder / Dispatcher）
      - 任务规划（Coordinator）
    """

    def __init__(
        self,
        name: str,
        llm: BaseChatModel,
        tools: list[BaseTool],
        checkpointer: AsyncSqliteSaver,
        state: RuntimeState,
        *,
        agent_prompt: str = "",
        max_iterations: int | None = None,
    ) -> None:
        self.name = name
        self.llm = llm
        self._tools = list(tools)
        self._checkpointer = checkpointer
        self.state = state
        self.agent_prompt = agent_prompt
        self.max_iterations = max_iterations or settings.agent_max_iterations

        self._agent: CompiledStateGraph | None = None
        self._agent_tools_hash: int = 0

    # ------------------------------------------------------------------
    # LangGraph Agent
    # ------------------------------------------------------------------

    def _get_agent(self) -> CompiledStateGraph:
        """获取或创建 LangGraph ReAct Agent。"""
        tools_hash = hash(tuple(id(t) for t in self._tools))
        if self._agent is not None and self._agent_tools_hash == tools_hash:
            return self._agent

        self._agent = create_react_agent(
            model=self.llm,
            tools=self._tools,
            checkpointer=self._checkpointer,
        )
        self._agent_tools_hash = tools_hash
        return self._agent

    def _build_config(self) -> dict:
        return {
            "configurable": {"thread_id": self.state.session_id},
            "recursion_limit": self.max_iterations * 2 + 10,
        }

    # ------------------------------------------------------------------
    # 执行
    # ------------------------------------------------------------------

    async def run(
        self,
        task: str,
        *,
        system_prompt: str = "",
        **kwargs: Any,
    ) -> str:
        """执行任务，返回完整响应文本。"""
        agent = self._get_agent()
        config = self._build_config()

        # system_prompt 以 SystemMessage 形式直接放到 messages 列表最前面
        msgs: list = []
        if system_prompt:
            msgs.append(SystemMessage(content=system_prompt))
        msgs.append(HumanMessage(content=task))

        result = await agent.ainvoke({"messages": msgs}, config=config)
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
        """流式执行，逐 token yield。"""
        agent = self._get_agent()
        config = self._build_config()

        msgs: list = []
        if system_prompt:
            msgs.append(SystemMessage(content=system_prompt))
        msgs.append(HumanMessage(content=task))

        async for event in agent.astream_events(
            {"messages": msgs}, config=config, version="v2",
        ):
            kind = event.get("event", "")
            if kind == "on_chat_model_stream":
                chunk = event.get("data", {}).get("chunk")
                if chunk and hasattr(chunk, "content") and chunk.content:
                    yield chunk.content

        self.state.turn_count += 1

    # ------------------------------------------------------------------
    # 属性
    # ------------------------------------------------------------------

    @property
    def tools(self) -> list[BaseTool]:
        return self._tools

    def reset(self) -> None:
        self.state.reset_turn()
