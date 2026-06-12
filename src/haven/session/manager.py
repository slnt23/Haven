"""SessionManager —— 会话生命周期管理。

管理多个 Session 及其运行状态。
每个 Session 对应一个 LangGraph checkpointer 中的 thread_id。
消息持久化由 LangGraph SqliteSaver 自动处理。
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver

from haven.session.models import Session, SessionState

logger = logging.getLogger("haven.session.manager")


class SessionManager:
    """会话管理器。

    职责：
      - 创建/获取/关闭 Session
      - 管理每个 Session 的 SessionState
      - 为每个 Session 提供独立的 LangGraph checkpointer

    Usage::

        manager = SessionManager(checkpointer_factory=create_checkpointer)
        session = manager.create(user_id="alice")
        state = manager.get_state(session.id)
        state.turn_count += 1
    """

    def __init__(
        self,
        checkpointer: BaseCheckpointSaver | None = None,
    ) -> None:
        self._sessions: dict[str, Session] = {}
        self._states: dict[str, SessionState] = {}
        self._checkpointer = checkpointer or InMemorySaver()

    # ------------------------------------------------------------------
    # Session CRUD
    # ------------------------------------------------------------------

    def create(
        self,
        session_id: str | None = None,
        *,
        user_id: str = "user",
        channel: str = "cli",
        metadata: dict[str, Any] | None = None,
    ) -> Session:
        """创建新会话。

        Args:
            session_id: 会话 ID。为 None 时自动生成 UUID。
            user_id: 用户/实体标识。
            channel: 交互渠道（cli / feishu / tcp）。
            metadata: 附加元数据。

        Returns:
            新创建的 Session。
        """
        sid = session_id or str(uuid.uuid4())
        session = Session(
            id=sid,
            user_id=user_id,
            channel=channel,
            metadata=metadata or {},
        )
        self._sessions[sid] = session
        self._states[sid] = SessionState()
        logger.info("Session created: %s (user=%s, channel=%s)", sid, user_id, channel)
        return session

    def get(self, session_id: str) -> Session | None:
        """获取已有 Session，不存在时返回 None。"""
        return self._sessions.get(session_id)

    def get_or_create(
        self,
        session_id: str,
        *,
        user_id: str = "user",
        channel: str = "cli",
    ) -> Session:
        """获取已有 Session 或创建新 Session。"""
        existing = self.get(session_id)
        if existing is not None:
            return existing
        return self.create(session_id, user_id=user_id, channel=channel)

    def get_state(self, session_id: str) -> SessionState | None:
        """获取 Session 的运行时状态。"""
        return self._states.get(session_id)

    def get_or_create_state(self, session_id: str) -> SessionState:
        """获取已有状态或创建默认状态。"""
        if session_id not in self._states:
            self._states[session_id] = SessionState()
        return self._states[session_id]

    def close(self, session_id: str) -> None:
        """关闭并移除 Session 及其状态。"""
        self._sessions.pop(session_id, None)
        self._states.pop(session_id, None)
        logger.info("Session closed: %s", session_id)

    def reset(self, session_id: str) -> SessionState:
        """重置 Session 状态：清空状态 → 新 thread_id。

        保留 Session 标识，但清空运行时状态。
        消息历史在 checkpointer 中由新 thread_id 隔离。
        """
        state = self.get_or_create_state(session_id)
        state.reset_turn()
        state.last_plan = None
        logger.info("Session reset: %s", session_id)
        return state

    # ------------------------------------------------------------------
    # Checkpointer
    # ------------------------------------------------------------------

    def get_checkpointer(self) -> BaseCheckpointSaver:
        """获取共享的 LangGraph checkpointer。

        所有 Session 共享同一 checkpointer，通过 thread_id 隔离。
        """
        return self._checkpointer

    # ------------------------------------------------------------------
    # 会话列表
    # ------------------------------------------------------------------

    def list_sessions(self) -> list[Session]:
        """返回所有活跃会话。"""
        return list(self._sessions.values())

    def __len__(self) -> int:
        return len(self._sessions)

    def __contains__(self, session_id: str) -> bool:
        return session_id in self._sessions
