"""AgentMemory — V1 兼容 facade，委托到 V2 MemoryManager。

对外 API 不变，内部由四层记忆（Working + Episodic + Semantic + Vector）支撑。
"""

from __future__ import annotations

import logging
from collections import deque
from typing import Any

from langchain_core.messages import BaseMessage, HumanMessage, AIMessage

logger = logging.getLogger("haven.memory")


class AgentMemory:
    """双层记忆 facade：短期 deque + 长期 MemoryManager。

    与 V1 API 完全兼容：
      - add_message / get_history / clear
      - save_message / extract_facts / get_long_term_context
      - session_id / entity_name / channel 属性

    内部委托到 V2 MemoryManager（四层记忆）。
    """

    def __init__(self, max_messages: int = 100):
        self.messages: deque[BaseMessage] = deque(maxlen=max_messages)
        self.metadata: dict[str, Any] = {}

        self._session_id: str = "default"
        self._entity_name: str = ""
        self._channel: str = "cli"

        # V2 MemoryManager（延迟初始化）
        self._manager: Any = None

    # ==================================================================
    # V2 Manager 延迟初始化
    # ==================================================================

    @property
    def manager(self) -> Any:
        if self._manager is None:
            from haven.memory.manager import MemoryManager
            self._manager = MemoryManager(
                session_id=self._session_id,
                entity_name=self._entity_name or "user",
                channel=self._channel,
                enable_vector=False,  # Vector 默认关闭，按需开启
            )
        return self._manager

    # ==================================================================
    # 短期记忆（直接操作 deque，与 V1 完全一致）
    # ==================================================================

    def add_message(self, message: BaseMessage) -> None:
        self.messages.append(message)

    def add_messages(self, messages: list[BaseMessage]) -> None:
        for msg in messages:
            self.add_message(msg)

    def get_history(self) -> list[BaseMessage]:
        return list(self.messages)

    def clear(self) -> None:
        self.messages.clear()
        self.metadata.clear()

    def __len__(self) -> int:
        return len(self.messages)

    # ==================================================================
    # 会话标识
    # ==================================================================

    @property
    def session_id(self) -> str:
        return self._session_id

    @session_id.setter
    def session_id(self, value: str) -> None:
        self._session_id = value
        if self._manager is not None:
            self._manager.session_id = value

    @property
    def channel(self) -> str:
        return self._channel

    @channel.setter
    def channel(self, value: str) -> None:
        self._channel = value
        if self._manager is not None:
            self._manager.channel = value

    @property
    def entity_name(self) -> str:
        return self._entity_name or self._session_id

    @entity_name.setter
    def entity_name(self, value: str) -> None:
        self._entity_name = value
        if self._manager is not None:
            self._manager.entity_name = value

    # ==================================================================
    # 长期持久化（委托到 V2 Manager）
    # ==================================================================

    def save_message(self, role: str, content: str) -> None:
        """持久化单条消息到长期存储（V1 兼容）。

        V2: 消息通过 MemoryManager.record_turn() 完整保存。
        此方法保留以支持逐条写入的场景。
        """
        try:
            import asyncio
            if role == "human":
                self.manager.working.add_message(HumanMessage(content=content))
            elif role == "ai":
                self.manager.working.add_message(AIMessage(content=content))

            self.manager.episodic._conn.execute(
                "INSERT INTO conversations (session_id, channel, role, content) VALUES (?,?,?,?)",
                (self._session_id, self._channel, role, content),
            )
            self.manager.episodic._conn.commit()
        except Exception as exc:
            logger.warning("save_message failed: %s", exc)

    def get_long_term_context(self, entity_name: str = "") -> str:
        """返回格式化的长期事实，用于注入 system prompt（V1 兼容）。"""
        name = entity_name or self.entity_name
        try:
            facts = self.manager.semantic._conn.execute(
                """SELECT f.key, f.value, f.confidence
                   FROM memory_facts f
                   JOIN memory_entities e ON f.entity_id = e.id
                   WHERE e.name = ? AND f.confidence >= 0.3
                   ORDER BY f.confidence DESC LIMIT 15""",
                (name,),
            ).fetchall()

            if not facts:
                return ""

            lines = ["\n[长期记忆 — 以下是你已知的关于当前用户的信息]"]
            for f in facts:
                lines.append(f"- {f['key']}: {f['value']}")
            return "\n".join(lines)
        except Exception as exc:
            logger.warning("get_long_term_context failed: %s", exc)
            return ""

    async def extract_facts(self, llm: Any) -> None:
        """从最近一轮对话中提取事实并存储（V1 兼容）。"""
        name = self.entity_name
        if not name or name == "default":
            return
        try:
            self.manager.set_llm(llm)
            rows = self.manager.episodic._conn.execute(
                "SELECT role, content FROM conversations WHERE session_id=? ORDER BY id DESC LIMIT 2",
                (self._session_id,),
            ).fetchall()

            user_msg = ""
            ai_msg = ""
            for r in reversed(rows):
                if r["role"] == "human":
                    user_msg = r["content"]
                elif r["role"] == "ai":
                    ai_msg = r["content"]

            if not user_msg:
                return

            snippet = f"用户: {user_msg}\nAI: {ai_msg}" if ai_msg else f"用户: {user_msg}"
            await self.manager._extract_facts(user_msg, ai_msg or "")
        except Exception as exc:
            logger.warning("extract_facts failed: %s", exc)
