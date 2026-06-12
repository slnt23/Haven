"""Haven REPL —— 异步对话循环，流式输出。

通过 Runtime.execute_stream() 与 Agent 交互。
使用 Rich Markdown 渲染 Agent 输出，终端友好展示。
"""

from __future__ import annotations

import asyncio
import logging
import sys

from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown

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
  /log [on|off|debug]  查看/切换日志级别
  /exit         退出对话
"""


async def _async_input(prompt: str) -> str:
    loop = asyncio.get_running_loop()
    return (await loop.run_in_executor(None, input, prompt)).strip()


async def run_repl() -> None:
    """启动 Haven REPL 对话循环。"""
    console = Console(highlight=False)

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

            if user_input.startswith("/"):
                _handle_command(console, runtime, user_input.strip())
                continue

            # 所有执行通过 Runtime.execute_stream() —— 禁止直接调用 Agent
            try:
                buffer: list[str] = []
                with Live(
                    Markdown(""), refresh_per_second=10, console=console,
                    vertical_overflow="visible",
                ) as live:
                    async for chunk in runtime.execute_stream(user_input):
                        if chunk.kind == "text":
                            buffer.append(chunk.content)
                            live.update(Markdown("".join(buffer)))
                        elif chunk.kind == "plan":
                            live.console.print(f"  [bold cyan]{chunk.content}[/bold cyan]")
                        elif chunk.kind == "status":
                            live.console.print(f"  [dim]{chunk.content}[/dim]")
            except KeyboardInterrupt:
                console.print("\n  [yellow]已中断，正在清理会话...[/yellow]")
                try:
                    await runtime.reset_session()
                except Exception:
                    pass
            except Exception as exc:
                console.print(f"\n  [red]执行出错: {exc}[/red]")
                try:
                    await runtime.reset_session()
                except Exception:
                    pass
    finally:
        await runtime.close()


# ------------------------------------------------------------------
# 内建命令
# ------------------------------------------------------------------


def _handle_command(console: Console, runtime, cmd: str) -> None:
    if cmd == "/exit":
        raise KeyboardInterrupt()
    elif cmd == "/model":
        model_name = getattr(runtime.llm, "model_name", "unknown")
        console.print(f"  当前模型: [bold]{model_name}[/bold]")
    elif cmd == "/tools":
        _show_tools(console, runtime)
    elif cmd == "/agents":
        _show_agents(console, runtime)
    elif cmd == "/clear":
        asyncio.create_task(_async_clear(console, runtime))
    elif cmd == "/memory-clear":
        _clear_memory(console, runtime)
    elif cmd.startswith("/log"):
        _toggle_log(cmd)
    else:
        console.print(f"  [yellow]未知命令: {cmd}[/yellow]")


async def _async_clear(console, runtime) -> None:
    await runtime.reset_session()
    console.print("  [green]会话记忆已清除[/green]")


def _show_tools(console: Console, runtime) -> None:
    """通过 CapabilityRegistry 显示已加载工具。"""
    registry = getattr(runtime, "registry", None)
    if registry is None:
        console.print("  [yellow]工具注册表不可用[/yellow]")
        return

    tools = registry.list_tools()
    if not tools:
        console.print("  (无已加载工具)")
        return

    console.print(f"  [bold]已加载工具 ({len(tools)}):[/bold]")
    for t in tools:
        provider = t.metadata.provider
        desc = t.description[:60]
        console.print(f"    * [cyan]{t.name}[/cyan]  [{provider}]  {desc}")


def _show_agents(console: Console, runtime) -> None:
    agents = getattr(runtime, "agents", {})
    if not agents:
        console.print("  (无可用 Agent)")
        return

    console.print(f"  [bold]可用 Agent ({len(agents)}):[/bold]")
    for name, agent in agents.items():
        prompt = getattr(agent, "agent_prompt", "")[:60]
        console.print(f"    * [cyan]{name}[/cyan]  {prompt}")


def _toggle_log(cmd: str) -> None:
    haven_logger = logging.getLogger("haven")
    parts = cmd.strip().split()
    arg = parts[1] if len(parts) > 1 else ""

    if arg in ("on", "info"):
        haven_logger.setLevel(logging.INFO)
        print("  日志级别: INFO", file=sys.stderr)
    elif arg == "debug":
        haven_logger.setLevel(logging.DEBUG)
        print("  日志级别: DEBUG", file=sys.stderr)
    elif arg == "off":
        haven_logger.setLevel(logging.WARNING)
        print("  日志级别: WARNING (仅警告)", file=sys.stderr)
    else:
        level = logging.getLevelName(haven_logger.level)
        print(f"  日志级别: {level}  |  用法: /log [on|off|debug]", file=sys.stderr)


def _clear_memory(console: Console, runtime) -> None:
    """通过 MemoryManager 清除长期记忆。"""
    memory = getattr(runtime, "_memory", None)
    if memory is None:
        console.print("  [yellow]长期记忆未启用[/yellow]")
        return
    try:
        memory.forget()
        console.print("  [green]长期记忆已清除[/green]")
    except Exception as exc:
        console.print(f"  [red]清除失败: {exc}[/red]")
