"""ChatSession — reusable single-turn conversation handler.

Encapsulates system-prompt assembly, memory, and persistence.
Used by both the CLI REPL and socket channels.
"""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage

from haven.core.base_agent import BaseAgent

logger = logging.getLogger("haven.session")


class ChatSession:
    """Process one conversation turn through a shared agent.

    Builds the full message list (system prompt + skills + history + user
    input), delegates to the agent for LLM invocation, then updates memory
    and persists.

    Usage::

        session = ChatSession(agent)
        response = await session.process("你好")
        # optionally trigger background fact extraction
        await agent.extract_facts_async()
    """

    def __init__(self, agent: BaseAgent) -> None:
        self.agent = agent

    async def process(
        self,
        user_input: str,
        history: list[Any] | None = None,
        persist: bool = True,
    ) -> str:
        """Process a single user message and return the agent's response.

        Args:
            user_input: The user's message text.
            history: Optional override for conversation history (used for
                     per-connection session isolation in socket channels).
                     When ``None``, ``agent.memory.get_history()`` is used.
            persist: Whether to save the turn to long-term memory.
        """
        on_demand = self.agent.match_skills(user_input)

        try:
            content = await self.agent.run(
                user_input,
                history=history or self.agent.memory.get_history(),
                on_demand_skills=on_demand,
                use_rag=True,
            )
        except Exception as exc:
            logger.warning("ChatSession LLM error: %s", exc)
            content = f"[错误] {exc}"

        self._update_memory(user_input, content, history)

        if persist:
            self.agent.save_turn(user_input, content)

        return content

    def _update_memory(
        self, user_input: str, content: str, history: list[Any] | None
    ) -> None:
        """Update short-term memory (only when using agent's own history)."""
        if history is None:
            self.agent.memory.add_message(HumanMessage(content=user_input))
            self.agent.memory.add_message(AIMessage(content=content))

    async def process_no_persist(self, user_input: str) -> str:
        """Process a message without persisting to long-term memory."""
        return await self.process(user_input, persist=False)
