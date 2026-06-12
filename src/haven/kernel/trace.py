"""Trace 系统 —— TraceContext + contextvar 传播 + LangChain 集成。

通过 Python contextvars 在异步调用链中自动传播 trace 信息，
无需显式传参。LangChain RunnableConfig 集成允许在 LangGraph
节点间传递 trace 元数据。
"""

from __future__ import annotations

import uuid
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any

from langchain_core.runnables import RunnableConfig

# ============================================================================
# TraceContext
# ============================================================================


@dataclass(frozen=True, slots=True)
class TraceContext:
    """分布式追踪上下文。

    trace_id 关联一次完整的用户请求，
    span_id 标识请求内的一个执行阶段。
    """

    trace_id: str
    span_id: str

    @classmethod
    def new(cls) -> TraceContext:
        """创建新的根 TraceContext。

        用于每次用户请求的入口点。
        """
        return cls(
            trace_id=str(uuid.uuid4()),
            span_id=str(uuid.uuid4()),
        )

    def child_span(self) -> TraceContext:
        """创建子 Span —— 同 trace_id，新 span_id。

        用于 Execution → Agent → Tool 的层级追踪。
        """
        return TraceContext(
            trace_id=self.trace_id,
            span_id=str(uuid.uuid4()),
        )


# ============================================================================
# ContextVar 传播
# ============================================================================


_current_trace: ContextVar[TraceContext | None] = ContextVar(
    "haven_trace_context", default=None
)
_current_trace_token: ContextVar[object | None] = ContextVar(
    "haven_trace_token", default=None
)


def set_current_trace(ctx: TraceContext) -> None:
    """设置当前异步上下文的 TraceContext。"""
    token = _current_trace.set(ctx)
    _current_trace_token.set(token)


def get_current_trace() -> TraceContext | None:
    """获取当前异步上下文的 TraceContext。"""
    return _current_trace.get(None)


def reset_current_trace() -> None:
    """重置当前上下文中的 TraceContext 为默认值。"""
    token = _current_trace_token.get(None)
    if token is not None:
        _current_trace.reset(token)
        _current_trace_token.set(None)


# ============================================================================
# LangChain RunnableConfig 集成
# ============================================================================


def config_with_trace(
    config: RunnableConfig | None = None,
    *,
    trace_id: str | None = None,
) -> RunnableConfig:
    """将 TraceContext 注入 LangChain RunnableConfig。

    在 LangGraph 节点间传递 trace 信息，与 LangChain callback 系统协作。

    Args:
        config: 现有的 RunnableConfig（可能为 None）。
        trace_id: 显式指定 trace_id。为 None 时尝试从 contextvar 读取。

    Returns:
        包含 trace 元数据的 RunnableConfig。

    Usage::

        ctx = TraceContext.new()
        set_current_trace(ctx)
        config = config_with_trace(base_config)
        await agent.ainvoke({"messages": [...]}, config=config)
    """
    cfg: dict[str, Any] = dict(config) if config else {}

    tid = trace_id
    if tid is None:
        current = get_current_trace()
        if current is not None:
            tid = current.trace_id
    if tid is None:
        tid = str(uuid.uuid4())

    # 写入 configurable 以供 checkpointer + callback handler 读取
    cfg.setdefault("configurable", {})
    cfg["configurable"]["haven_trace_id"] = tid

    # metadata 供 LangSmith / LangFuse 等外部追踪系统使用
    cfg.setdefault("metadata", {})
    cfg["metadata"]["haven_trace_id"] = tid

    return cfg


def trace_id_from_config(config: RunnableConfig | None) -> str | None:
    """从 LangChain RunnableConfig 中恢复 trace_id。"""
    if config is None:
        return None
    configurable = config.get("configurable", {})
    return configurable.get("haven_trace_id")
