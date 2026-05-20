from __future__ import annotations

from abc import ABC, abstractmethod

from forest.core.base_agent import BaseAgent


class BaseChannel(ABC):
    """Abstract interface for a chat channel.

    A channel is a message source/sink — it receives incoming messages,
    passes them through the shared Agent, and sends back responses.
    """

    def __init__(self, name: str, enabled: bool = True) -> None:
        self.name = name
        self.enabled = enabled
        self._agent: BaseAgent | None = None

    @property
    def agent(self) -> BaseAgent:
        if self._agent is None:
            raise RuntimeError(f"Channel '{self.name}': agent not set")
        return self._agent

    async def handle_message(self, message: str) -> str:
        """Route a message through the shared agent and return the response."""
        return await self.agent.run(message)

    @abstractmethod
    async def start(self, agent: BaseAgent) -> None:
        """Start the channel with a shared agent instance."""
        self._agent = agent

    @abstractmethod
    async def stop(self) -> None:
        """Stop the channel and release resources."""
