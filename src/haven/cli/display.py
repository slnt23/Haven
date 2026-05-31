"""UI helpers for the Haven CLI — banner, loading animation, prompts."""

from __future__ import annotations

import asyncio
import itertools
import sys
from typing import Any

from haven.config import get_default_model
from haven.core.base_agent import BaseAgent

_LOADING_WORDS = ["思考中", "分析中", "处理中", "生成中", "整理中"]


def print_line(*args: Any) -> None:
    """Write a line to stdout, flushing immediately."""
    text = " ".join(str(a) for a in args)
    sys.stdout.write(text + "\n")
    sys.stdout.flush()


async def show_loading(stop_event: asyncio.Event) -> None:
    """Animated loading indicator — cycles through words with dots."""
    words = itertools.cycle(_LOADING_WORDS)
    dots_seq = ["   ", ".  ", ".. ", "..."]
    while not stop_event.is_set():
        word = next(words)
        for dots in dots_seq:
            if stop_event.is_set():
                break
            sys.stdout.write(f"\r  {word}{dots}")
            sys.stdout.flush()
            await asyncio.sleep(0.25)
    sys.stdout.write("\r" + " " * 24 + "\r")
    sys.stdout.flush()


async def prompt_user() -> str:
    """Read a line from stdin with a styled prompt."""
    try:
        print_line()
        print_line("——" * 30)
        sys.stdout.write("》 ")
        sys.stdout.flush()
        loop = asyncio.get_running_loop()
        line = await loop.run_in_executor(None, sys.stdin.readline)
        print_line("——" * 30)
        return line
    except (EOFError, KeyboardInterrupt):
        raise


def print_banner(agent: BaseAgent) -> None:
    """Print the Haven startup banner with model / skills / MCP status."""
    model = getattr(agent.llm, "model_name", None) or get_default_model()
    sub_agents = getattr(agent, "sub_agents", None)

    # aggregate across sub-agents when using orchestrator
    if sub_agents:
        skill_count = sum(len(a.skills) for a in sub_agents.values())
        tool_count = sum(len(a.tools) for a in sub_agents.values())
    else:
        skill_count = len(agent.skills)
        tool_count = len(agent.tools)

    mcp_manager = getattr(agent, "mcp_manager", None)

    mcp_line = ""
    if mcp_manager is not None:
        active = mcp_manager.active_server_count
        failed = mcp_manager.failed_server_count
        mcp_tool_count = len(mcp_manager.tools)
        parts = [f"MCP: {active} server(s)"]
        if mcp_tool_count:
            parts.append(f"{mcp_tool_count} tool(s)")
        if failed:
            parts.append(f"{failed} offline")
        mcp_line = f"│  {', '.join(parts):<74}│\n"

    agent_line = ""
    if sub_agents:
        names = ", ".join(sorted(sub_agents.keys()))
        agent_line = f"│  Agents: {len(sub_agents)} ({names}):<76│\n"

    banner = f"""
╭──────────────────────────── Haven v0.2.0 ────────────────────────────────╮
│          _   _                                                             │
│         | | | | __ ___   _____ _ __                                        │
│         | |_| |/ _` \\ \\ / / _ \\ '_ \\                                   │
│         |  _  | (_| |\\ V /  __/ | | |                                     │
│         |_| |_|\\__,_| \\_/ \\___|_| |_|                                   │
│                                                                            │
│  Model:   {model:<63}│
│  Agents:  {len(sub_agents) if sub_agents else 1:<63}│
│  Skills:  {skill_count:<63}│
│  Tools:   {tool_count:<63}│
│  MCP:     {mcp_line}                                                       │
│                                                                            │
│  Commands:                                                                 │
│  /help        /skills     /tools     /models    /model                     │
│  /mcp         /clear      /exit /q                                         │
│                                                                            │
╰────────────────────────────────────────────────────────────────────────────╯
"""  # noqa: E501
    print_line(banner)
