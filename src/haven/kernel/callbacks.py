"""HavenCallbackHandler — LangChain 回调 → Haven AgentEvent 桥接。

将 LangChain 的 BaseCallbackHandler 事件翻译为 Haven 统一的 AgentEvent 模型。
事件通过可注入的 handler 函数消费，支持测试收集器和未来的 EventBus。

集成方式：
  1. 直接传入 LangChain agent invoke/stream 的 config.callbacks
  2. 通过 RunnableConfig 自动传递 trace_id
"""

from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable
from uuid import uuid4

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.agents import AgentAction, AgentFinish

from haven.kernel.event import AgentEvent, EventType
from haven.kernel.trace import trace_id_from_config

logger = logging.getLogger("haven.kernel.callbacks")

# 事件消费函数签名
EventHandler = Callable[[AgentEvent], Awaitable[None]]


class HavenCallbackHandler(BaseCallbackHandler):
    """LangChain 回调 → Haven AgentEvent 桥接器。

    将 LangChain 的原生回调事件翻译为 Haven 统一事件模型。
    支持注入自定义 handler 消费事件。

    Usage::

        handler = HavenCallbackHandler(on_event=my_handler)
        config = config_with_trace(base_config)
        config["callbacks"] = [handler]
        await agent.ainvoke(..., config=config)
    """

    def __init__(
        self,
        on_event: EventHandler | None = None,
        *,
        collect: bool = False,
    ) -> None:
        super().__init__()
        self._on_event = on_event
        self._collect = collect
        self.events: list[AgentEvent] = []  # collect=True 时累积

    # ------------------------------------------------------------------
    # LangChain → Haven 事件映射
    # ------------------------------------------------------------------

    async def on_tool_start(
        self,
        serialized: dict[str, Any],
        input_str: str,
        *,
        run_id: str,
        parent_run_id: str | None = None,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        inputs: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        """工具调用开始 → TOOL_START。"""
        tool_name = serialized.get("name", "unknown")
        trace_id = metadata.get("haven_trace_id") if metadata else None
        event = AgentEvent.create(
            EventType.TOOL_START,
            trace_id or "",
            payload={
                "tool_name": tool_name,
                "tool_input": input_str,
                "run_id": str(run_id),
            },
        )
        await self._emit(event)

    async def on_tool_end(
        self,
        output: Any,
        *,
        run_id: str,
        parent_run_id: str | None = None,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        """工具调用结束 → TOOL_END。"""
        trace_id = metadata.get("haven_trace_id") if metadata else None
        event = AgentEvent.create(
            EventType.TOOL_END,
            trace_id or "",
            payload={
                "run_id": str(run_id),
                "tool_output": str(output)[:2000],
            },
        )
        await self._emit(event)

    async def on_tool_error(
        self,
        error: BaseException,
        *,
        run_id: str,
        parent_run_id: str | None = None,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        """工具调用失败 → ERROR。"""
        trace_id = metadata.get("haven_trace_id") if metadata else None
        event = AgentEvent.create(
            EventType.ERROR,
            trace_id or "",
            payload={
                "source": "tool",
                "run_id": str(run_id),
                "error_type": type(error).__name__,
                "error_message": str(error),
            },
        )
        await self._emit(event)

    async def on_llm_new_token(
        self,
        token: str,
        *,
        run_id: str,
        parent_run_id: str | None = None,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        """LLM 流式 token → AGENT_TOKEN。"""
        trace_id = metadata.get("haven_trace_id") if metadata else None
        # 跳过空白 token
        stripped = token.strip()
        if not stripped:
            return
        # 每个 token 都发事件会过多，仅内部处理
        # 实际 EventBus 层可选过滤
        if self._on_event is not None:
            event = AgentEvent.create(
                EventType.AGENT_TOKEN,
                trace_id or "",
                payload={"token": stripped},
            )
            await self._emit(event)

    async def on_llm_error(
        self,
        error: BaseException,
        *,
        run_id: str,
        parent_run_id: str | None = None,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        """LLM 调用失败 → ERROR。"""
        trace_id = metadata.get("haven_trace_id") if metadata else None
        event = AgentEvent.create(
            EventType.ERROR,
            trace_id or "",
            payload={
                "source": "llm",
                "run_id": str(run_id),
                "error_type": type(error).__name__,
                "error_message": str(error),
            },
        )
        await self._emit(event)

    async def on_chain_start(
        self,
        serialized: dict[str, Any],
        inputs: dict[str, Any],
        *,
        run_id: str,
        parent_run_id: str | None = None,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        """Chain 开始 → AGENT_START（仅 Agent 类型的 chain）。"""
        # LangGraph agent 的 chain name 通常包含 "agent"
        chain_name = serialized.get("name", "") if isinstance(serialized, dict) else ""
        if "agent" in chain_name.lower() or "Agent" in chain_name:
            trace_id = metadata.get("haven_trace_id") if metadata else None
            event = AgentEvent.create(
                EventType.AGENT_START,
                trace_id or "",
                payload={
                    "agent_name": chain_name,
                    "run_id": str(run_id),
                },
            )
            await self._emit(event)

    async def on_agent_action(
        self,
        action: AgentAction,
        *,
        run_id: str,
        parent_run_id: str | None = None,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        """Agent 决定调用工具 → AGENT_START（含决策信息）。"""
        trace_id = metadata.get("haven_trace_id") if metadata else None
        event = AgentEvent.create(
            EventType.AGENT_START,
            trace_id or "",
            payload={
                "tool": action.tool,
                "tool_input": str(action.tool_input)[:500],
                "run_id": str(run_id),
            },
        )
        await self._emit(event)

    async def on_agent_finish(
        self,
        finish: AgentFinish,
        *,
        run_id: str,
        parent_run_id: str | None = None,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        """Agent 完成 → 不单独发事件（EXECUTION_END 由上层发布）。"""
        pass

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------

    async def _emit(self, event: AgentEvent) -> None:
        """将事件分发给已注册的 handler 和收集器。"""
        if self._collect:
            self.events.append(event)
        if self._on_event is not None:
            try:
                await self._on_event(event)
            except Exception:
                logger.debug("Event handler failed for %s", event.type, exc_info=True)
