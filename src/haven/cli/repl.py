"""Haven REPL —— 异步对话循环，流式输出。

通过 Runtime.execute_stream() 与 Agent 交互。
支持内建命令：/model /tools /help /exit
"""

from __future__ import annotations

import asyncio
import sys

from rich.console import Console

from haven import __version__
from haven.runtime.factory import create_runtime

_BANNER = f"""
  Haven v{__version__}  |  多智能体交互框架
"""

_HELP = """\
[bold]内建命令:[/bold]
  /model        查看当前模型
  /tools        查看已加载工具
  /agents       查看可用 Agent
  /clear        清除当前会话记忆
  /memory-clear 清除长期记忆
  /exit         退出对话
"""


async def _async_input(prompt: str) -> str:
    """异步读取一行输入。"""
    loop = asyncio.get_running_loop()
    return (await loop.run_in_executor(None, input, prompt)).strip()


async def run_repl() -> None:
    """启动 Haven REPL 对话循环。"""
    console = Console(highlight=False)

    # 创建 Runtime（包含 Coordinator + Dispatcher + Agents + Tools）
    runtime = await create_runtime(channel="cli")
    model_name = getattr(runtime.llm, "model_name", "unknown")

    try:
        console.print(_BANNER, style="bold cyan")
        console.print(f"  模型: [bold]{model_name}[/bold]", style="dim")
        console.print(_HELP)

        while True:
            try:
                user_input = await _async_input("\n> ")
            except (KeyboardInterrupt, EOFError):
                console.print()
                break

            if not user_input:
                continue

            # 内建命令
            if user_input.startswith("/"):
                cmd = user_input.strip()
                if cmd == "/exit":
                    break
                elif cmd == "/model":
                    model_name = getattr(runtime.llm, "model_name", "unknown")
                    console.print(f"  当前模型: [bold]{model_name}[/bold]")
                elif cmd == "/tools":
                    _show_tools(console, runtime)
                elif cmd == "/agents":
                    _show_agents(console, runtime)
                elif cmd == "/clear":
                    await runtime.reset_session()
                    console.print("  [green]会话记忆已清除[/green]")
                elif cmd == "/memory-clear":
                    _clear_memory(console, runtime)
                else:
                    console.print(f"  [yellow]未知命令: {cmd}[/yellow]")
                continue

            # 流式对话：Runtime.execute_stream() → Dispatcher → Agent → LLM
            try:
                async for chunk in runtime.execute_stream(user_input):
                    sys.stdout.write(chunk)
                    sys.stdout.flush()
                console.print()
            except KeyboardInterrupt:
                console.print("\n  [yellow]已中断[/yellow]")
    finally:
        await runtime.close()


# ------------------------------------------------------------------
# 内建命令实现
# ------------------------------------------------------------------


def _show_tools(console: Console, runtime) -> None:
    """显示已加载的工具列表。"""
    loader = getattr(runtime, "tool_loader", None)
    if loader is None:
        console.print("  [yellow]工具加载器不可用[/yellow]")
        return

    tools = loader.registry.list()
    if not tools:
        console.print("  (无已加载工具)")
        return

    console.print(f"  [bold]已加载工具 ({len(tools)}):[/bold]")
    for t in tools:
        provider = getattr(t, "metadata", None)
        provider_name = getattr(provider, "provider", "?") if provider else "?"
        desc = getattr(t, "description", "")[:60]
        console.print(f"    • [cyan]{t.name}[/cyan]  [{provider_name}]  {desc}")


def _show_agents(console: Console, runtime) -> None:
    """显示可用 Agent 列表。"""
    agents = getattr(runtime, "agents", {})
    if not agents:
        console.print("  (无可用 Agent)")
        return

    console.print(f"  [bold]可用 Agent ({len(agents)}):[/bold]")
    for name, agent in agents.items():
        prompt = getattr(agent, "agent_prompt", "")[:60]
        console.print(f"    • [cyan]{name}[/cyan]  {prompt}")


def _clear_memory(console: Console, runtime) -> None:
    """清除长期记忆（FactStore 中的所有事实）。"""
    fs = getattr(runtime.dispatcher, "_fact_store", None)
    if fs is None:
        console.print("  [yellow]长期记忆未启用[/yellow]")
        return
    try:
        fs.clear()
        console.print("  [green]长期记忆已清除[/green]")
    except Exception as exc:
        console.print(f"  [red]清除失败: {exc}[/red]")
