"""BaseAgent —— 专业 Agent 基类，封装 LangGraph ReAct Agent。

每个 Agent 实例 = LangChain 工具集 + system_prompt 扩展。
工具在创建时一次性绑定，LLM 通过 Function Calling 自行决定调用哪个。
不做任何 Tool 解析、选择、推理 —— 这些全部交给 LangChain 和 LLM。
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
    """LangGraph ReAct Agent 的轻量包装。

    职责：
      - 持有 LLM + 工具 + checkpointer
      - 懒初始化 LangGraph Agent（工具变更时自动重建）
      - pre_model_hook 中裁剪消息确保不超 context window
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
        self.name = name  # Agent 名称（coder / researcher / diagnosis / general）
        self.llm = llm  # LLM 实例
        self._tools = list(tools)  # 工具列表（创建后不变）
        self._checkpointer = checkpointer  # LangGraph 持久化
        self.state = state  # 共享运行时状态
        self.agent_prompt = agent_prompt  # Agent 专属 system_prompt 片段
        self.max_iterations = max_iterations or settings.agent_max_iterations

        # LangGraph Agent 懒初始化
        self._agent: CompiledStateGraph | None = None
        self._agent_tools_hash: int = 0  # 检测工具是否变更

    # ------------------------------------------------------------------
    # LangGraph Agent（懒初始化）
    # ------------------------------------------------------------------

    @staticmethod
    def _pre_model_hook(state: dict, config: RunnableConfig | None = None) -> dict:
        """LLM 调用前的钩子：注入 system_prompt + 裁剪消息。"""
        sp = state.get("system_prompt", "")
        msgs = list(state.get("messages", []))
        if sp:
            msgs = [SystemMessage(content=sp)] + msgs  # system_prompt 放到最前
        trimmed = trim_messages(
            msgs,
            max_tokens=settings.context_window_tokens or 8000,
            strategy="last",  # 保留最新消息
            token_counter=count_tokens_approximately,
            include_system=True,
            start_on="human",  # 从 human 消息开始裁剪
        )
        return {"llm_input_messages": trimmed}

    def _get_agent(self) -> CompiledStateGraph:
        """获取或创建 LangGraph ReAct Agent。工具变更时自动重建。"""
        tools_hash = hash(tuple(id(t) for t in self._tools))
        if self._agent is not None and self._agent_tools_hash == tools_hash:
            return self._agent  # 缓存命中

        # 工具未变，直接复用
        self._agent = create_react_agent(
            model=self.llm,
            tools=self._tools,
            checkpointer=self._checkpointer,
            pre_model_hook=self._pre_model_hook,
        )
        self._agent_tools_hash = tools_hash
        return self._agent

    def _build_config(self, system_prompt: str = "") -> dict:
        """构建 LangGraph 执行配置。"""
        return {
            "configurable": {
                "thread_id": self.state.session_id,  # 会话隔离
                "system_prompt": system_prompt,  # 通过 config 传入 hook
            },
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
        """同步式执行（内部异步），返回完整响应文本。"""
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
        """流式执行，逐 token yield。"""
        agent = self._get_agent()
        config = self._build_config(system_prompt=system_prompt)

        async for event in agent.astream_events(
            {"messages": [HumanMessage(content=task)], "system_prompt": system_prompt},
            config=config,
            version="v2",
        ):
            kind = event.get("event", "")
            if kind == "on_chat_model_stream":  # 仅提取 LLM 流式 token
                chunk = event.get("data", {}).get("chunk")
                if chunk and hasattr(chunk, "content") and chunk.content:
                    yield chunk.content

        self.state.turn_count += 1

    # ------------------------------------------------------------------
    # 属性
    # ------------------------------------------------------------------

    @property
    def tools(self) -> list[BaseTool]:
        """当前绑定的工具列表。"""
        return self._tools

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------

    def reset(self) -> None:
        """重置 turn 计数（不清理 checkpointer 历史）。"""
        self.state.reset_turn()
