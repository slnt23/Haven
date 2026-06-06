"""haven chat — 交互式 REPL。

CLI → RuntimeService → Runtime（禁止 CLI 直接调 Runtime）。
采用终端动态刷新：原地 spinner + 状态提示，最终结果完整块输出。
"""

from __future__ import annotations

import asyncio
import logging
from typing import Annotated

import typer

from haven.cli.bridge.cli_context import CLIContext, HistoryManager
from haven.cli.ui.banner import print_banner
from haven.cli.ui.console import (
    blank,
    render_error,
    render_info,
    render_markdown,
    render_success,
    render_user_message,
    rule,
)
from haven.cli.ui.progress import DynamicRenderer

logger = logging.getLogger("haven.cli.chat")


def run_chat(
    ctx: typer.Context,
    model: Annotated[str | None, typer.Option("--model", "-m", help="指定模型")] = None,
    task: Annotated[str | None, typer.Option("--task", "-t", help="启动后立即执行的任务")] = None,
    verbose: Annotated[bool, typer.Option("--verbose", "-v", help="详细模式")] = False,
    task_only: bool = False,
    session: str | None = None,
    no_memory: bool = False,
) -> None:
    """启动 Haven 交互式 REPL。动态刷新渲染，原地状态更新。

    task_only=True 时仅执行初始任务然后退出，不进入 REPL。
    """
    cli_ctx = ctx.obj if isinstance(ctx.obj, CLIContext) else CLIContext()
    cli_ctx.model = model
    cli_ctx.verbose = verbose
    if session:
        cli_ctx.session_id = session
    history = HistoryManager()

    # ---- 初始化 RuntimeService ----
    asyncio.run(_start_service(cli_ctx, model, no_memory=no_memory))

    # ---- Banner ----
    svc = cli_ctx._service
    status = svc._status()
    from haven import __version__

    print_banner(
        model=status["model"],
        skills=status["skills"],
        tools=status["tools"],
        workflows=status["workflows"],
        memory_turns=status["memory_turns"],
        providers=status["providers"],
        vector_available=status.get("vector_available", False),
        version=__version__,
    )
    render_info("输入 /help 查看命令，Ctrl+C 退出。")
    blank()

    # ---- 初始任务 ----
    if task:
        render_markdown(f"**[Task]** {task}\n")
        asyncio.run(_process_chat(task, cli_ctx))
        if task_only:
            rule()
            asyncio.run(_stop_service(cli_ctx))
            return

    # ---- REPL ----
    while True:
        try:
            user_input = typer.prompt(">", prompt_suffix=" ", show_default=False)
        except (KeyboardInterrupt, EOFError):
            rule()
            asyncio.run(_stop_service(cli_ctx))
            render_info("再见。")
            break

        user_input = user_input.strip()
        if not user_input:
            continue

        history.add(user_input)

        if user_input.startswith("/"):
            handled = _handle_slash(user_input, cli_ctx)
            if not handled:
                continue
            break  # /exit raises Exit

        asyncio.run(_process_chat(user_input, cli_ctx))


# ====================================================================
# Service 生命周期
# ====================================================================


async def _start_service(
    cli_ctx: CLIContext, model: str | None, *, no_memory: bool = False,
) -> None:
    from haven.cli.bridge.runtime_service import RuntimeService
    from haven.config import settings

    svc = RuntimeService()
    try:
        await svc.start(
            model=model,
            session_id=cli_ctx.session_id or "cli_main",
            entity_name="cli_user",
            load_mcp=settings.mcp_enabled,
            use_memory=not no_memory,
        )
    except Exception as exc:
        render_error(f"启动 Runtime 失败: {exc}")
        raise typer.Exit(code=1) from exc

    cli_ctx._service = svc
    cli_ctx.planner = svc.get_planner()
    cli_ctx.runtime = svc.get_runtime()


async def _stop_service(cli_ctx: CLIContext) -> None:
    svc = getattr(cli_ctx, "_service", None)
    if svc:
        await svc.stop()


# ====================================================================
# 对话处理 — 动态刷新渲染
# ====================================================================


async def _process_chat(user_input: str, cli_ctx: CLIContext) -> None:
    """处理一轮对话：用户回显 + spinner 原地刷新 + AI 面板渲染。"""
    svc = cli_ctx._service

    # 回显用户输入
    render_user_message(user_input)

    renderer = DynamicRenderer()
    async with renderer:
        try:
            async for token in svc.chat_stream(user_input):
                renderer.feed(token)
        except Exception as exc:
            logger.error("chat error: %s", exc)
            renderer.feed(f"\n[错误] {exc}")

    response = renderer.render()
    # 消息由 LangGraph SqliteSaver checkpointer 自动持久化，无需手动保存


# ====================================================================
# Slash 命令
# ====================================================================


def _handle_slash(text: str, cli_ctx: CLIContext) -> bool:
    """处理斜杠命令。返回 True 表示应退出 REPL。"""
    cmd = text.strip().lower()
    svc = getattr(cli_ctx, "_service", None)

    if cmd in ("/exit", "/quit", "/q"):
        rule()
        asyncio.run(_stop_service(cli_ctx))
        render_info("再见。")
        raise typer.Exit()

    if cmd == "/help":
        render_info(
            "REPL commands:\n"
            "  /help           帮助\n"
            "  /model [name]   查看/切换模型\n"
            "  /models         列出模型\n"
            "  /skills         列出 skill\n"
            "  /tools          列出工具\n"
            "  /memory         记忆状态\n"
            "  /workflows      工作流列表\n"
            "  /clear          清空对话\n"
            "  /exit           退出"
        )
        return False

    if cmd == "/skills":
        try:
            info = svc.list_skills() if svc else "(RuntimeService 未初始化)"
            render_info(info)
        except Exception as exc:
            render_error(str(exc))
        return False

    if cmd == "/tools":
        try:
            info = svc.list_tools() if svc else "(RuntimeService 未初始化)"
            render_info(info)
        except Exception as exc:
            render_error(str(exc))
        return False

    if cmd == "/memory":
        try:
            info = svc.get_memory_stats() if svc else "(RuntimeService 未初始化)"
            render_info(info)
        except Exception as exc:
            render_error(str(exc))
        return False

    if cmd == "/workflows":
        try:
            info = svc.list_workflows() if svc else "(RuntimeService 未初始化)"
            render_info(info)
        except Exception as exc:
            render_error(str(exc))
        return False

    if cmd.startswith("/model"):
        parts = cmd.split()
        if len(parts) > 1 and svc:
            try:
                actual = svc.switch_model(parts[1])
                render_success(f"已切换模型: {actual}")
            except Exception as exc:
                render_error(str(exc))
        else:
            info = svc.current_model() if svc else "(Runtime 未初始化)"
            render_info(f"当前模型: {info}")
        return False

    if cmd == "/models":
        try:
            info = svc.list_models() if svc else "(RuntimeService 未初始化)"
            render_info(info)
        except Exception as exc:
            render_error(str(exc))
        return False

    if cmd == "/clear":
        if svc:
            asyncio.run(svc.reset_session())
            render_success("对话历史已清空（含 checkpointer 线程）。")
        else:
            render_info("(Runtime 未初始化)")
        return False

    render_info(f"未知命令: {cmd}  (输入 /help)")
    return False
