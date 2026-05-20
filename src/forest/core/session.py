"""ChatSession — reusable single-turn conversation handler.

Encapsulates system-prompt assembly, LLM invocation with tool-calling loop,
and persistence.  Used by both the CLI REPL and socket channels.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from forest.core.base_agent import BaseAgent

logger = logging.getLogger("forest.session")


class ChatSession:
    """Process one conversation turn through a shared agent.

    Builds the full message list (system prompt + skills + history + user
    input), runs the LLM with a tool-calling loop, updates short-term
    memory, and persists to long-term memory.

    Usage::

        session = ChatSession(agent)
        response = await session.process("你好")
        # optionally trigger background fact extraction
        await agent.extract_facts_async()
    """

    def __init__(self, agent: BaseAgent) -> None:
        self.agent = agent

    # ------------------------------------------------------------------
    # public API
    # ------------------------------------------------------------------

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
        messages = self._build_messages(user_input, history)

        try:
            content = await self._invoke_with_tools(messages)
        except Exception as exc:
            logger.warning("ChatSession LLM error: %s", exc)
            content = f"[错误] {exc}"

        self._update_memory(user_input, content, history)

        if persist:
            self.agent.save_turn(user_input, content)

        return content

    # ------------------------------------------------------------------
    # internal
    # ------------------------------------------------------------------

    def _build_messages(
        self, user_input: str, history: list[Any] | None
    ) -> list[Any]:
        """Assemble the full message list for the LLM call."""
        system_text = self.agent._build_system_prompt()

        matched = self.agent.match_skills(user_input)
        for skill in matched:
            system_text += f"\n\n{skill.prompt_extension}"

        messages: list[Any] = []
        if system_text:
            messages.append(SystemMessage(content=system_text))

        if history is not None:
            messages.extend(history)
        else:
            messages.extend(self.agent.memory.get_history())

        messages.append(HumanMessage(content=user_input))
        return messages

    async def _invoke_with_tools(self, messages: list[Any]) -> str:
        """Call the LLM with a tool-calling loop."""
        if self.agent.llm is None:
            self.agent._init_llm()

        response = await self.agent.llm.ainvoke(messages)

        iteration = 0
        max_iter = getattr(self.agent, "max_iterations", 10)
        while getattr(response, "tool_calls", None) and iteration < max_iter:
            messages.append(response)

            for tc in response.tool_calls:
                tool_name = tc.get("name", "")
                tool_args = tc.get("args", {})
                tool_id = tc.get("id", "")
                try:
                    result = await self.agent._execute_tool_call(tool_name, tool_args)
                except Exception as exc:
                    result = f"Error: {exc}"
                messages.append(ToolMessage(content=str(result), tool_call_id=tool_id))

            response = await self.agent.llm.ainvoke(messages)
            iteration += 1

        return response.content if hasattr(response, "content") else str(response)

    def _update_memory(
        self, user_input: str, content: str, history: list[Any] | None
    ) -> None:
        """Update short-term memory (only when using agent's own history)."""
        if history is None:
            self.agent.memory.add_message(HumanMessage(content=user_input))
            self.agent.memory.add_message(AIMessage(content=content))

    # ------------------------------------------------------------------
    # convenience
    # ------------------------------------------------------------------

    async def process_no_persist(self, user_input: str) -> str:
        """Process a message without persisting to long-term memory."""
        return await self.process(user_input, persist=False)
