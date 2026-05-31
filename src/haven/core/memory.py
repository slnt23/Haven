import logging
from collections import deque
from typing import Any

from langchain_core.messages import BaseMessage


class AgentMemory:
    """双层记忆：内存 deque（短期）+ SQLite（长期）。

    短期记忆保留最近 N 条消息作为即时上下文。
    长期记忆持久化全部对话，并提取关于实体（人）的结构化事实。
    """

    def __init__(self, max_messages: int = 100):
        self.messages: deque[BaseMessage] = deque(maxlen=max_messages)
        self.metadata: dict[str, Any] = {}

        # 长期存储（延迟初始化，避免导入时创建数据库）
        self._store = None
        self._session_id: str = "default"
        self._entity_name: str = ""
        self._channel: str = "cli"

    # ------------------------------------------------------------------
    # 短期记忆
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # 长期存储访问
    # ------------------------------------------------------------------

    @property
    def store(self):
        """延迟初始化 SQLite 记忆存储。"""
        if self._store is None:
            from haven.core.memory_store import SQLiteMemoryStore
            self._store = SQLiteMemoryStore()
        return self._store

    # ------------------------------------------------------------------
    # 会话身份
    # ------------------------------------------------------------------

    @property
    def session_id(self) -> str:
        return self._session_id

    @session_id.setter
    def session_id(self, value: str) -> None:
        self._session_id = value

    @property
    def channel(self) -> str:
        return self._channel

    @channel.setter
    def channel(self, value: str) -> None:
        self._channel = value

    @property
    def entity_name(self) -> str:
        return self._entity_name or self._session_id

    @entity_name.setter
    def entity_name(self, value: str) -> None:
        self._entity_name = value

    # ------------------------------------------------------------------
    # 长期持久化
    # ------------------------------------------------------------------

    def save_message(self, role: str, content: str) -> None:
        """将单条消息持久化到长期存储。"""
        try:
            self.store.save_message(self.session_id, role, content, channel=self.channel)
        except Exception as exc:
            logging.getLogger("haven.memory").warning("save_message failed: %s", exc)

    def get_long_term_context(self, entity_name: str = "") -> str:
        """返回格式化的长期事实，用于注入 system prompt。"""
        name = entity_name or self.entity_name
        try:
            return self.store.format_facts_by_name(name)
        except Exception as exc:
            logging.getLogger("haven.memory").warning("get_long_term_context failed: %s", exc)
            return ""

    async def extract_facts(self, llm: Any) -> None:
        """从最近一轮对话中提取事实并存储。"""
        name = self.entity_name
        if not name or name == "default":
            return
        try:
            user_msg, ai_msg = self.store.get_last_conversation_pair(self.session_id)
            if not user_msg:
                return
            snippet = f"用户: {user_msg}\nAI: {ai_msg}" if ai_msg else f"用户: {user_msg}"
            source = f"session:{self.session_id}"
            await self.store.extract_and_store(name, snippet, llm, source)
        except Exception as exc:
            logging.getLogger("haven.memory").warning("extract_facts failed: %s", exc)
