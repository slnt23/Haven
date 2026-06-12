"""BaseAgent —— 专业 Agent 基类，封装 LangChain ``create_agent``。

每个 Agent 实例 = LangChain 工具集 + system_prompt。
工具在创建时一次性绑定，LLM 通过 Function Calling 自行决定调用哪个。

System_prompt 以 SystemMessage 形式注入 messages，支持动态构建。
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, AsyncIterator

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import BaseTool
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph.state import CompiledStateGraph
from langchain.agents import create_agent

from haven.config import settings
from haven.core.state import RuntimeState
from haven.runtime.stream import StreamChunk

logger = logging.getLogger("haven.agent")


class BaseAgent:
    """LangChain ``create_agent`` 的轻量包装。

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
        """获取或创建 LangChain Agent。"""
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

    def _build_config(self) -> dict:
        return {
            "configurable": {"thread_id": self.state.session_id},
            "recursion_limit": self.max_iterations * 2 + 10,
        }

    async def _repair_checkpoint(self, config: dict) -> bool:
        """检查并修复孤立的 tool_calls，注入合成 ToolMessage 以通过验证。

        当上一轮对话被中断时，checkpointer 可能保存了 AIMessage(tool_calls=...)
        但对应的 ToolMessage 尚未生成，导致 LangGraph _validate_chat_history 失败。
        """
        try:
            state = await self._agent.aget_state(config)
            if not state or not state.values:
                return False
            messages = state.values.get("messages", [])

            tool_call_ids: set[str] = set()
            for m in messages:
                if hasattr(m, "tool_calls") and m.tool_calls:
                    for tc in m.tool_calls:
                        tool_call_ids.add(tc["id"])

            tool_results: set[str] = {
                m.tool_call_id
                for m in messages
                if hasattr(m, "tool_call_id")
            }

            orphaned = tool_call_ids - tool_results
            if not orphaned:
                return False

            from langchain_core.messages import ToolMessage

            repair_msgs = [
                ToolMessage(
                    content="[中断恢复] 此工具调用被中断，未获取结果。",
                    tool_call_id=tid,
                )
                for tid in orphaned
            ]
            await self._agent.aupdate_state(config, {"messages": repair_msgs})
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
        thread_id: str | None = None,
        **kwargs: Any,
    ) -> str:
        """执行任务，返回完整响应文本。

        thread_id 为 None 时使用 session_id（多轮对话），
        传入具体值时用于隔离上下文（如工作流节点）。
        """
        agent = self._get_agent()
        config = self._build_config()
        if thread_id is not None:
            config["configurable"]["thread_id"] = thread_id

        await self._repair_checkpoint(config)

        # system_prompt 以 SystemMessage 形式直接放到 messages 列表最前面
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
            # 超时后清理可能残留的孤立 tool_calls
            await self._repair_checkpoint(config)
            self.state.turn_count += 1
            return "执行超时，请检查网络连接或简化问题后重试。"
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
    ) -> AsyncIterator[StreamChunk]:
        """流式执行，逐 token yield。"""
        agent = self._get_agent()
        config = self._build_config()

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
                            yield StreamChunk(
                                kind="text",
                                content=self._sanitize(chunk.content),
                            )
                    elif kind == "on_tool_start":
                        tool_name = event.get("name", "unknown")
                        yield StreamChunk(kind="status", content=f"调用工具: {tool_name}")
                    elif kind == "on_tool_end":
                        tool_name = event.get("name", "unknown")
                        yield StreamChunk(kind="status", content=f"工具完成: {tool_name}")
        except TimeoutError:
            # 超时后清理可能残留的孤立 tool_calls
            await self._repair_checkpoint(config)
            yield StreamChunk(kind="status", content="执行超时，请检查网络连接或简化问题后重试。")

        self.state.turn_count += 1

    # ------------------------------------------------------------------
    # 工具方法
    # ------------------------------------------------------------------

    @staticmethod
    def _sanitize(text: str) -> str:
        """移除非法 surrogate 字符，避免 UTF-8 编码崩溃。

        DeepSeek 等模型的流式输出偶尔包含 ``\\udcXX`` 这类
        孤立 surrogate 字符，Python 的 UTF-8 codec 会拒绝编码。
        """
        return text.encode("utf-8", errors="surrogateescape").decode("utf-8", errors="replace")

    # ------------------------------------------------------------------
    # 属性
    # ------------------------------------------------------------------

    @property
    def tools(self) -> list[BaseTool]:
        return self._tools

    def reset(self) -> None:
        self.state.reset_turn()
