"""统一事件系统 —— AgentEvent 定义 + EventType 枚举。

Haven 内部所有组件通过 AgentEvent 通信。
LangChain 回调事件通过 HavenCallbackHandler 桥接至此模型。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class EventType(str, Enum):
    """Haven 系统事件类型。

    覆盖完整执行生命周期：
      Execution → Agent → Tool → Memory → Error
    """

    EXECUTION_START = "execution.start"
    EXECUTION_END = "execution.end"

    AGENT_START = "agent.start"
    AGENT_TOKEN = "agent.token"

    TOOL_START = "tool.start"
    TOOL_END = "tool.end"

    MEMORY_UPDATE = "memory.update"

    ERROR = "error"


@dataclass(frozen=True, slots=True)
class AgentEvent:
    """不可变事件对象，贯穿整个系统的事件总线。

    字段：
        id: 事件唯一标识 (UUID v4)。
        trace_id: 关联的 Trace 标识，用于端到端追踪。
        timestamp: ISO 8601 格式 UTC 时间戳。
        type: 事件类型。
        payload: 任意键值数据，类型特定。
    """

    id: str
    trace_id: str
    timestamp: str
    type: EventType
    payload: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def create(
        cls,
        event_type: EventType,
        trace_id: str,
        *,
        payload: dict[str, Any] | None = None,
    ) -> AgentEvent:
        """工厂方法：创建带自动 ID 和时间戳的事件。"""
        return cls(
            id=str(uuid.uuid4()),
            trace_id=trace_id,
            timestamp=datetime.now(timezone.utc).isoformat(),
            type=event_type,
            payload=payload or {},
        )

    def with_payload(self, **kwargs: Any) -> AgentEvent:
        """返回合并了额外 payload 字段的新事件（不可变更新）。"""
        merged = {**self.payload, **kwargs}
        return AgentEvent(
            id=self.id,
            trace_id=self.trace_id,
            timestamp=self.timestamp,
            type=self.type,
            payload=merged,
        )
