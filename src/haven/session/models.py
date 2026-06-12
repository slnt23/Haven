"""Session 数据模型 —— 会话标识与运行时状态。

Session: 不可变的会话标识（id 即 LangGraph thread_id）。
SessionState: 会话的可变运行时状态（turn_count, active_skills 等）。

消息持久化由 LangGraph SqliteSaver 自动管理，Session 只持有 thread_id 引用。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class Session:
    """会话标识 —— 不可变。

    id 即 LangGraph checkpointer 的 thread_id。
    """

    id: str
    user_id: str = "user"
    channel: str = "cli"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class SessionState:
    """会话的可变运行时状态。

    不持久化到 checkpointer —— 仅用于当前进程的运行期状态。
    消息历史由 LangGraph SqliteSaver 以 thread_id 为键自动管理。
    """

    turn_count: int = 0
    active_skills: list[str] = field(default_factory=list)
    active_tools: list[str] = field(default_factory=list)
    current_node: str = ""
    last_plan: dict | None = None

    def reset_turn(self) -> None:
        """重置当前轮次的临时状态。"""
        self.active_skills = []
        self.active_tools = []
        self.current_node = ""
