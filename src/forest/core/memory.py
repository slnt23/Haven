from collections import deque
from typing import Any

from langchain_core.messages import BaseMessage


class AgentMemory:
    def __init__(self, max_messages: int = 100):
        self.messages: deque[BaseMessage] = deque(maxlen=max_messages)
        self.metadata: dict[str, Any] = {}

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
