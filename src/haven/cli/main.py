"""haven CLI V2 — 统一入口。Typer + Rich。

4 条命令：haven（REPL）/ haven --task / haven status / haven serve。
"""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path
from typing import Annotated, Optional

from rich.logging import RichHandler
import typer

from haven.cli.services.cli_service import CLIContext
from haven.cli.ui.console import dim, render_error, render_info, render_success

# ---------------------------------------------------------------------------
# 日志
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.WARNING,
    format="%(message)s",
    datefmt="[%X]",
    handlers=[RichHandler(rich_tracebacks=True, show_time=False, show_path=False)],
)

logger = logging.getLogger("haven.cli")

# ---------------------------------------------------------------------------
# 主应用
# ---------------------------------------------------------------------------

app = typer.Typer(
    name="haven",
    help="Haven — 多智能体交互框架",
    rich_markup_mode="rich",
    no_args_is_help=False,
    context_settings={"help_option_names": ["-h", "--help"]},
    invoke_without_command=True,
)


# ====================================================================
# 全局回调 + 默认 REPL
# ====================================================================


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    version: Annotated[bool, typer.Option("--version", help="显示版本")] = False,
    verbose: Annotated[bool, typer.Option("--verbose", "-v", help="详细输出")] = False,
    quiet: Annotated[bool, typer.Option("--quiet", "-q", help="静默输出")] = False,
    json_output: Annotated[bool, typer.Option("--json", help="JSON 输出")] = False,
    no_color: Annotated[bool, typer.Option("--no-color", help="禁用彩色输出")] = False,
    config: Annotated[Optional[str], typer.Option("--config", "-c", help="指定配置文件")] = None,
    model: Annotated[str | None, typer.Option("--model", "-m", help="指定模型")] = None,
    session: Annotated[str | None, typer.Option("--session", "-s", help="恢复会话 ID")] = None,
    task: Annotated[str | None, typer.Option("--task", "-t", help="单次任务（执行后退出）")] = None,
    no_memory: Annotated[bool, typer.Option("--no-memory", help="禁用长期记忆")] = False,
) -> None:
    """Haven — 基于 Python 3.14+ 和 LangChain 的多智能体交互框架。

    默认启动交互式 REPL。
    """
    cli_ctx = CLIContext(
        verbose=verbose,
        quiet=quiet,
        json_output=json_output,
        no_color=no_color,
    )
    ctx.obj = cli_ctx

    if version:
        typer.echo("haven v2.0.0")
        raise typer.Exit()

    if verbose:
        logging.getLogger("haven").setLevel(logging.DEBUG)

    if config:
        p = Path(config)
        if not p.is_file():
            render_error(f"配置文件不存在: {config}")
            raise typer.Exit(code=1)

    # 默认 → REPL（含 --task 单次任务模式）
    if ctx.invoked_subcommand is None:
        from haven.cli.commands.chat import run_chat

        run_chat(ctx, model=model, task=task, verbose=verbose, task_only=bool(task))


# ====================================================================
# haven status — 查看守护进程状态
# ====================================================================


@app.command(name="status", help="查看守护进程状态")
def status_cmd(
    ctx: typer.Context,
    json_output: Annotated[bool, typer.Option("--json", "-j", help="JSON 输出")] = False,
) -> None:
    """查看 Haven 守护进程运行状态。"""
    from haven.config import settings
    from haven.core.pidfile import is_running, read as pid_read

    pid = pid_read(settings.pid_file)
    running = pid is not None and is_running(pid)

    if json_output:
        import json as json_mod

        info = {
            "daemon": "running" if running else "stopped",
            "pid": pid,
            "pid_file": str(settings.pid_file),
        }
        typer.echo(json_mod.dumps(info, ensure_ascii=False, indent=2))
    else:
        if running:
            render_success(f"守护进程运行中 (PID: {pid})")
        else:
            render_info(f"守护进程未运行 (PID 文件: {settings.pid_file})")


# ====================================================================
# haven serve — 启动守护进程
# ====================================================================


@app.command(name="serve", help="启动守护进程")
def serve_cmd(
    ctx: typer.Context,
) -> None:
    """启动 Haven 守护进程（多通道：TCP + 邮件 + 飞书）。"""
    from haven.services.daemon import HavenDaemon

    daemon = HavenDaemon()
    try:
        asyncio.run(daemon.run_forever())
    except KeyboardInterrupt:
        dim("\n守护进程已停止。")
    except SystemExit as e:
        if e.code != 0:
            render_error(f"启动失败: {e}")
            raise typer.Exit(code=e.code) from None


# ====================================================================
# 入口
# ====================================================================


def main_cli() -> None:
    """``haven`` 命令入口。"""
    try:
        app()
    except typer.Exit as e:
        sys.exit(e.exit_code)
    except KeyboardInterrupt:
        dim("\n中断。")
        sys.exit(130)
    except Exception as exc:
        render_error(str(exc))
        if logger.isEnabledFor(logging.DEBUG):
            logger.exception("Fatal error")
        sys.exit(1)


if __name__ == "__main__":
    main_cli()
