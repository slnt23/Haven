"""Agent —— 专业 Agent，封装 LangChain ``create_agent``。

Agent 职责：
  - 任务理解与模型调用
  - Capability (Tool) 调用
  - ReAct 循环管理

Agent 不负责：
  - CLI / Interface（由 Interface 层负责）
  - Session 状态（由 SessionManager 负责）
  - Memory 存储（由 Memory 层负责）

优先基于 LangChain 官方 Agent/Runnable 封装。
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, AsyncIterator

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import BaseTool
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph.state import CompiledStateGraph
from langchain.agents import create_agent

from haven.config import settings

logger = logging.getLogger("haven.agent")


class Agent:
    """LangChain ``create_agent`` 的轻量包装。

    不持有 session / CLI / memory 状态。
    thread_id 通过方法参数传入，工具在创建时绑定。
    """

    def __init__(
        self,
        name: str,
        llm: BaseChatModel,
        tools: list[BaseTool],
        checkpointer: BaseCheckpointSaver,
        *,
        agent_prompt: str = "",
        max_iterations: int | None = None,
    ) -> None:
        self.name = name
        self.llm = llm
        self._tools = list(tools)
        self._checkpointer = checkpointer
        self.agent_prompt = agent_prompt
        self.max_iterations = max_iterations or settings.agent_max_iterations

        self._agent: CompiledStateGraph | None = None
        self._agent_tools_hash: int = 0

    # ------------------------------------------------------------------
    # LangGraph Agent
    # ------------------------------------------------------------------

    def _get_agent(self) -> CompiledStateGraph:
        tools_hash = hash(tuple(id(t) for t in self._tools))
        if self._agent is not None and self._agent_tools_hash == tools_hash:
            return self._agent

        self._agent = create_agent(
            model=self.llm,
            tools=self._tools,
            checkpointer=self._checkpointer,
        )
        self._agent_tools_hash = tools_hash
        return self._agent

    def _build_config(self, thread_id: str = "default") -> dict:
        return {
            "configurable": {"thread_id": thread_id},
            "recursion_limit": self.max_iterations * 2 + 10,
        }

    async def _repair_checkpoint(self, config: dict) -> bool:
        try:
            st = await self._agent.aget_state(config)
            if not st or not st.values:
                return False
            messages = st.values.get("messages", [])

            tool_call_ids: set[str] = set()
            for m in messages:
                if hasattr(m, "tool_calls") and m.tool_calls:
                    for tc in m.tool_calls:
                        tool_call_ids.add(tc["id"])

            tool_results: set[str] = {
                m.tool_call_id for m in messages if hasattr(m, "tool_call_id")
            }

            orphaned = tool_call_ids - tool_results
            if not orphaned:
                return False

            from langchain_core.messages import ToolMessage

            repair = [
                ToolMessage(content="[中断恢复] 此工具调用被中断，未获取结果。", tool_call_id=tid)
                for tid in orphaned
            ]
            await self._agent.aupdate_state(config, {"messages": repair})
            logger.warning("修复了 %d 个孤立的 tool_calls: %s", len(orphaned), orphaned)
            return True
        except Exception as exc:
            logger.warning("检查点修复检查失败（非致命）: %s", exc)
            return False

    # ------------------------------------------------------------------
    # 执行
    # ------------------------------------------------------------------

    async def run(
        self,
        task: str,
        *,
        system_prompt: str = "",
        thread_id: str = "default",
        **kwargs: Any,
    ) -> str:
        """执行任务，返回完整响应文本。"""
        agent = self._get_agent()
        config = self._build_config(thread_id)
        await self._repair_checkpoint(config)

        msgs: list = []
        if system_prompt:
            msgs.append(SystemMessage(content=system_prompt))
        msgs.append(HumanMessage(content=task))

        try:
            result = await asyncio.wait_for(
                agent.ainvoke({"messages": msgs}, config=config),
                timeout=settings.agent_max_execution_time,
            )
        except asyncio.TimeoutError:
            await self._repair_checkpoint(config)
            return "执行超时，请检查网络连接或简化问题后重试。"

        output = result["messages"][-1]
        return output.content if hasattr(output, "content") else str(output)

    async def astream(
        self,
        task: str,
        *,
        system_prompt: str = "",
        thread_id: str = "default",
        **kwargs: Any,
    ) -> AsyncIterator:
        """流式执行，逐 token yield StreamChunk。"""
        from haven.runtime.stream import StreamChunk

        agent = self._get_agent()
        config = self._build_config(thread_id)
        await self._repair_checkpoint(config)

        msgs: list = []
        if system_prompt:
            msgs.append(SystemMessage(content=system_prompt))
        msgs.append(HumanMessage(content=task))

        try:
            async with asyncio.timeout(settings.agent_max_execution_time):
                async for event in agent.astream_events(
                    {"messages": msgs}, config=config,
                ):
                    kind = event.get("event", "")
                    if kind == "on_chat_model_stream":
                        chunk = event.get("data", {}).get("chunk")
                        if chunk and hasattr(chunk, "content") and chunk.content:
                            yield StreamChunk(kind="text", content=self._sanitize(chunk.content))
                    elif kind == "on_tool_start":
                        yield StreamChunk(kind="status", content=f"调用工具: {event.get('name', 'unknown')}")
                    elif kind == "on_tool_end":
                        yield StreamChunk(kind="status", content=f"工具完成: {event.get('name', 'unknown')}")
        except TimeoutError:
            await self._repair_checkpoint(config)
            yield StreamChunk(kind="status", content="执行超时，请检查网络连接或简化问题后重试。")

    # ------------------------------------------------------------------
    # 工具
    # ------------------------------------------------------------------

    @property
    def tools(self) -> list[BaseTool]:
        return self._tools

    def bind_tools(self, tools: list[BaseTool]) -> None:
        """替换工具集，下次调用时重新创建 LangGraph agent。"""
        self._tools = list(tools)
        self._agent = None

    def reset(self) -> None:
        """重置 agent 状态。"""
        self._agent = None

    @staticmethod
    def _sanitize(text: str) -> str:
        return text.encode("utf-8", errors="surrogateescape").decode("utf-8", errors="replace")
