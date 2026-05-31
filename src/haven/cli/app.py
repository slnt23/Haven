"""Haven CLI — interactive REPL."""

from __future__ import annotations

import asyncio

from haven.core.base_agent import BaseAgent
from haven.core.session import ChatSession
from haven.cli.display import print_line, show_loading, prompt_user, print_banner
from haven.cli.commands import handle as handle_command
from haven.agents.factory import create_agent

class HavenApp:
    """Interactive REPL for the Haven multi-agent framework."""

    def __init__(self, agent: BaseAgent | None = None) -> None:
        self.agent = agent
        self.session: ChatSession | None = None
        self.running = False

    async def start(self, greeting_task: str | None = None) -> None:
        self.running = True

        if self.agent is None:
            self.agent = await create_agent(
                session_id="cli_main",
                entity_name="cli_user",
                channel="cli",
            )
        self.session = ChatSession(self.agent)
        print_banner(self.agent)

        if greeting_task:
            await self._chat(greeting_task)

        while self.running:
            try:
                user_input = await prompt_user()
            except (EOFError, KeyboardInterrupt):
                print_line("\n再见。")
                break

            if not user_input:
                print_line("请先输入内容。")
                continue

            if self._handle_command(user_input):
                continue

            await self._chat(user_input)

    # ------------------------------------------------------------------
    # chat
    # ------------------------------------------------------------------

    async def _chat(self, user_input: str) -> None:
        print_line()

        stop_event = asyncio.Event()
        loading_task = asyncio.create_task(show_loading(stop_event))

        try:
            response = await self.session.process(user_input)
        finally:
            stop_event.set()
            await loading_task

        print_line(response)

        # background fact extraction
        asyncio.create_task(self.agent.extract_facts_async())

    # ------------------------------------------------------------------
    # commands
    # ------------------------------------------------------------------

    def _handle_command(self, text: str) -> bool:
        result = handle_command(self.agent, text)
        if result is None:
            return False
        output, should_exit = result
        print_line(output)
        if should_exit:
            self.running = False
        return True
