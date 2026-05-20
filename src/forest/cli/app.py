"""Haven CLI — interactive REPL."""

from __future__ import annotations

import asyncio
from typing import Any

from forest.config import settings
from forest.core.base_agent import BaseAgent
from forest.core.session import ChatSession
from forest.skills.loader import SkillLoader
from forest.cli.display import print_line, show_loading, prompt_user, print_banner
from forest.cli.commands import handle as handle_command
from forest.agents import GeneralAgent

class HavenApp:
    """Interactive REPL for the Haven multi-agent framework."""

    def __init__(self, agent: BaseAgent | None = None) -> None:
        self.agent = agent
        self.mcp_manager = None
        self.session: ChatSession | None = None
        self.running = False

    # ------------------------------------------------------------------
    # public API
    # ------------------------------------------------------------------

    async def start(self, greeting_task: str | None = None) -> None:
        self.running = True

        await self._init_agent()
        self._load_skills()
        await self._init_mcp()
        self.session = ChatSession(self.agent)
        print_banner(self.agent, self.mcp_manager)

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
    # initialization
    # ------------------------------------------------------------------

    async def _init_agent(self) -> None:
        if self.agent is not None:
            return

        self.agent = GeneralAgent()
        self.agent.memory.session_id = "cli_main"
        self.agent.memory.entity_name = "cli_user"
        self.agent.memory.channel = "cli"
        if self.agent.llm is None:
            self.agent._init_llm()

    def _load_skills(self) -> None:
        skill_dir = settings.project_root / settings.skill_directory
        if not skill_dir.is_dir():
            return
        loaded = SkillLoader.load_from_dir(skill_dir)
        for skill in loaded:
            self.agent.skills[skill.name] = skill

    async def _init_mcp(self) -> None:
        if not settings.mcp_enabled:
            return
        try:
            from forest.mcp import MCPManager, MCPServerConfig
            from forest.config import get_mcp_config
        except ImportError as exc:
            print_line(f"[MCP] SDK 未安装, 跳过 MCP 集成 ({exc})")
            return

        raw_configs = get_mcp_config()
        if not raw_configs:
            return

        configs: list[Any] = []
        for raw in raw_configs:
            try:
                configs.append(MCPServerConfig(**raw))
            except Exception as exc:
                print_line(f"[MCP] 配置无效, 跳过: {exc}")
                continue

        configs = [c for c in configs if c.enabled]
        if not configs:
            return

        self.mcp_manager = MCPManager(configs)
        try:
            mcp_tools = await self.mcp_manager.start()
        except Exception as exc:
            print_line(f"[MCP] 连接失败: {exc}")
            return

        if mcp_tools and self.agent:
            self.agent.register_mcp_tools(mcp_tools)
            self.agent.bind_tools_to_llm()

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
        result = handle_command(self.agent, self.mcp_manager, text)
        if result is None:
            return False
        output, should_exit = result
        print_line(output)
        if should_exit:
            self.running = False
        return True
