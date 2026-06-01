"""haven CLI V2 — 统一入口。Typer + Rich。

自动命令注册，统一帮助，Rich 终端渲染，全局异常处理。
"""

from __future__ import annotations

import logging
from pathlib import Path
import sys
from typing import Annotated, Optional

from rich.logging import RichHandler
import typer

from haven.cli.services.cli_service import CLIContext
from haven.cli.ui.console import dim, render_error

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

# ---- 注册子命令组 (有二级命令的) ----
from haven.cli.commands.skill import skill_app  # noqa: E402
from haven.cli.commands.tool import tool_app  # noqa: E402
from haven.cli.commands.workflow import workflow_app  # noqa: E402

app.add_typer(workflow_app, name="workflow")
app.add_typer(skill_app, name="skill")
app.add_typer(tool_app, name="tool")


# ---------------------------------------------------------------------------
# 全局回调 + 默认命令
# ---------------------------------------------------------------------------


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
    task: Annotated[str | None, typer.Option("--task", "-t", help="启动后立即执行的任务")] = None,
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

    # 默认 → REPL
    if ctx.invoked_subcommand is None:
        from haven.cli.commands.chat import run_chat

        run_chat(ctx, model=model, task=task, verbose=verbose)


# ====================================================================
# 直接命令 (无二级子命令)
# ====================================================================


@app.command(name="run", help="单轮任务执行")
def run_cmd(
    ctx: typer.Context,
    task: Annotated[str, typer.Option("--task", "-t", help="任务文本（必填）")] = "",
    file: Annotated[Optional[str], typer.Option("--file", "-f", help="从文件读取任务")] = None,
    model: Annotated[str | None, typer.Option("--model", "-m", help="指定模型")] = None,
    stream: Annotated[bool, typer.Option("--stream", "-s", help="流式输出")] = False,
    json_output: Annotated[bool, typer.Option("--json", "-j", help="JSON 格式输出")] = False,
    no_memory: Annotated[bool, typer.Option("--no-memory", help="禁用长期记忆")] = False,
    no_plan: Annotated[bool, typer.Option("--no-plan", help="跳过 Planner")] = False,
    output: Annotated[Optional[str], typer.Option("--output", "-o", help="结果写入文件")] = None,
    verbose: Annotated[bool, typer.Option("--verbose", "-v", help="详细模式")] = False,
) -> None:
    """执行单轮任务，输出结果后退出。"""
    from haven.cli.commands.run import run_task

    run_task(
        ctx,
        task=task,
        file=file,
        model=model,
        stream=stream,
        json_output=json_output,
        no_memory=no_memory,
        no_plan=no_plan,
        output=output,
        verbose=verbose,
    )


@app.command(name="doctor", help="环境诊断")
def doctor_cmd(
    ctx: typer.Context,
    check: Annotated[str | None, typer.Option("--check", help="只检查指定项")] = None,
    json_output: Annotated[bool, typer.Option("--json", "-j", help="JSON 输出")] = False,
) -> None:
    """运行环境诊断，检查依赖和配置完整性。"""
    from haven.cli.commands.doctor import run_doctor

    run_doctor(ctx, check=check, json_output=json_output)


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
