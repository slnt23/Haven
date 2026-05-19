from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from forest.config import settings
from forest.core.base_agent import BaseAgent
from forest.skills.loader import SkillLoader


class HavenApp:
    """Interactive REPL for the Haven multi-agent framework."""

    def __init__(self, agent: BaseAgent | None = None) -> None:
        self.agent = agent
        self.running = False
        self._greeted = False

    # ------------------------------------------------------------------
    # public API
    # ------------------------------------------------------------------

    async def start(self, greeting_task: str | None = None) -> None:
        """Launch the REPL.  Returns when the user exits."""
        self.running = True

        await self._init_agent()
        self._load_skills()
        self._print_banner()

        # optional initial task
        if greeting_task:
            await self._chat(greeting_task)

        # main loop
        while self.running:
            try:
                user_input = await self._prompt()
            except (EOFError, KeyboardInterrupt):
                self._print("\n再见。")
                break

            if not user_input:
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

        from forest.agents import GeneralAgent

        self.agent = GeneralAgent()
        # ensure LLM is ready
        if self.agent.llm is None:
            self.agent._init_llm()

    def _load_skills(self) -> None:
        skill_dir = settings.project_root / settings.skill_directory
        if not skill_dir.is_dir():
            return
        loaded = SkillLoader.load_from_dir(skill_dir)
        for skill in loaded:
            self.agent.skills[skill.name] = skill

    # ------------------------------------------------------------------
    # chat
    # ------------------------------------------------------------------

    async def _chat(self, user_input: str) -> None:
        """Send user input to the agent with full conversation context."""
        if self.agent.llm is None:
            self.agent._init_llm()

        messages: list[Any] = []

        # 1. system prompt: role config + default skills (haven persona)
        system_text = self.agent._build_system_prompt()

        # 2. on-demand skills — only inject when trigger keywords match
        matched = self.agent.match_skills(user_input)
        for skill in matched:
            system_text += f"\n\n{skill.prompt_extension}"

        if system_text:
            messages.append(SystemMessage(content=system_text))

        # 3. conversation history
        messages.extend(self.agent.memory.get_history())

        # 4. current user message
        messages.append(HumanMessage(content=user_input))

        self.agent.memory.add_message(HumanMessage(content=user_input))

        self._print()  # blank line before response
        try:
            response = await self.agent.llm.ainvoke(messages)
            content = response.content if hasattr(response, "content") else str(response)
        except Exception as exc:
            content = f"[错误] {exc}"

        self.agent.memory.add_message(AIMessage(content=content))
        self._print(content)

    # ------------------------------------------------------------------
    # commands
    # ------------------------------------------------------------------

    def _handle_command(self, text: str) -> bool:
        """Return True if *text* was a command (already handled)."""
        if not text.startswith("/"):
            return False

        parts = text.strip().split()
        cmd = parts[0].lower()

        if cmd in ("/exit", "/quit", "/q"):
            self.running = False
            self._print("再见。")

        elif cmd == "/help":
            self._print(
                "命令列表:\n"
                "  /help       显示帮助\n"
                "  /skills     列出已加载的 skill\n"
                "  /clear      清空对话历史\n"
                "  /model      显示当前模型\n"
                "  /exit, /q   退出\n"
                "\n输入任何其他内容将发送给 agent。"
            )

        elif cmd == "/skills":
            if not self.agent.skills:
                self._print("(未加载任何 skill)")
            else:
                default_skills = [s for s in self.agent.skills.values() if s.default]
                ondemand_skills = [s for s in self.agent.skills.values() if not s.default]
                lines = [f"已加载 {len(self.agent.skills)} 个 skill:"]
                if default_skills:
                    lines.append("  [默认]")
                    for s in default_skills:
                        lines.append(f"    {s.name} — {s.description}")
                if ondemand_skills:
                    lines.append("  [按需]")
                    for s in ondemand_skills:
                        lines.append(f"    {s.name} — {s.description}")
                self._print("\n".join(lines))

        elif cmd == "/clear":
            self.agent.reset()
            self._print("对话历史已清空。")

        elif cmd == "/model":
            model_name = getattr(self.agent.llm, "model_name", None) or settings.agent_default_model
            self._print(f"当前模型: {model_name}")

        else:
            self._print(f"未知命令: {cmd}  (输入 /help 查看帮助)")

        return True

    # ------------------------------------------------------------------
    # IO helpers
    # ------------------------------------------------------------------

    async def _prompt(self) -> str:
        try:
            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(None, sys.stdin.readline)
        except (EOFError, KeyboardInterrupt):
            raise

    def _print_banner(self) -> None:
        skill_count = len(self.agent.skills)
        model = getattr(self.agent.llm, "model_name", None) or settings.agent_default_model
        self._print(
            f"\n  Haven (健健) — 多智能体交互框架  v0.1.0\n"
            f"  模型: {model}  |  已加载 {skill_count} 个 skill\n"
            f"  输入 /help 查看命令  |  /exit 退出\n"
        )

    @staticmethod
    def _print(*args: Any) -> None:
        text = " ".join(str(a) for a in args)
        sys.stdout.write(text + "\n")
        sys.stdout.flush()
