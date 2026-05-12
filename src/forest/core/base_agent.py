from abc import ABC, abstractmethod
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage

from forest.config import settings


class BaseAgent(ABC):
    def __init__(self, name: str, llm: BaseChatModel | None = None):
        self.name = name
        self.llm = llm
        self.tools: dict[str, Any] = {}
        self.max_iterations = settings.agent_max_iterations
        self.max_execution_time = settings.agent_max_execution_time

    def register_tool(self, name: str, tool: Any) -> None:
        self.tools[name] = tool

    @abstractmethod
    async def run(self, task: str, **kwargs: Any) -> str:
        ...

    @abstractmethod
    async def step(self, messages: list[BaseMessage]) -> BaseMessage:
        ...

    def reset(self) -> None:
        pass
