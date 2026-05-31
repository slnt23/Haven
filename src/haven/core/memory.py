import logging
from collections import deque
from typing import Any

from langchain_core.messages import BaseMessage


class AgentMemory:
    """Dual-layer memory: in-memory deque (short-term) + SQLite (long-term).

    Short-term memory holds the last N messages for immediate context.
    Long-term memory persists all conversations and extracts structured
    facts about entities (people) from conversations.
    """

    def __init__(self, max_messages: int = 100):
        self.messages: deque[BaseMessage] = deque(maxlen=max_messages)
        self.metadata: dict[str, Any] = {}

        # long-term store (lazy init to avoid DB creation on import)
        self._store = None
        self._session_id: str = "default"
        self._entity_name: str = ""
        self._channel: str = "cli"

    # ------------------------------------------------------------------
    # short-term
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
    # long-term store access
    # ------------------------------------------------------------------

    @property
    def store(self):
        """Lazy-init the SQLite memory store."""
        if self._store is None:
            from haven.core.memory_store import SQLiteMemoryStore
            self._store = SQLiteMemoryStore()
        return self._store

    # ------------------------------------------------------------------
    # session identity
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
    # long-term persistence
    # ------------------------------------------------------------------

    def save_message(self, role: str, content: str) -> None:
        """Persist a single message to the long-term store."""
        try:
            self.store.save_message(self.session_id, role, content, channel=self.channel)
        except Exception as exc:
            logging.getLogger("haven.memory").warning("save_message failed: %s", exc)

    def get_long_term_context(self, entity_name: str = "") -> str:
        """Return formatted long-term facts for injection into system prompt."""
        name = entity_name or self.entity_name
        try:
            return self.store.format_facts_by_name(name)
        except Exception as exc:
            logging.getLogger("haven.memory").warning("get_long_term_context failed: %s", exc)
            return ""

    async def extract_facts(self, llm: Any) -> None:
        """Extract facts from the most recent conversation pair and store them."""
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
