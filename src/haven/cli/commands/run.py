"""haven run — 单轮任务执行。

CLI → RuntimeService → Runtime（禁止 CLI 直接调 Runtime）。
"""

from __future__ import annotations

import asyncio
import logging
from typing import Annotated, Optional

import typer

from haven.cli.ui.console import (
    get_console, render_markdown, render_error, render_info,
    render_success, render_json, dim, blank,
)
from haven.cli.ui.progress import spinner
from haven.cli.services.cli_service import CLIContext
from haven.cli.validators import validate_task

logger = logging.getLogger("haven.cli.run")


def run_task(
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
    cli_ctx = ctx.obj if isinstance(ctx.obj, CLIContext) else CLIContext()
    cli_ctx.model = model
    cli_ctx.verbose = verbose
    cli_ctx.json_output = json_output

    # ---- 任务文本 ----
    task_text = task
    if file:
        try:
            with open(file, "r", encoding="utf-8") as f:
                task_text = f.read().strip()
        except FileNotFoundError:
            render_error(f"文件不存在: {file}")
            raise typer.Exit(code=1)

    valid, msg = validate_task(task_text)
    if not valid:
        render_error(msg)
        raise typer.Exit(code=1)

    # ---- 初始化 RuntimeService ----
    svc = asyncio.run(_init_service(model))

    if verbose:
        render_info(f"[config] model={model or 'default'} stream={stream} "
                     f"no_plan={no_plan} no_memory={no_memory}")

    # ---- 执行 ----
    async def _exec():
        async with spinner("执行中"):
            return await svc.run_task(
                task_text,
                no_plan=no_plan,
                no_memory=no_memory,
            )

    result_dict = asyncio.run(_exec())
    result_text = result_dict["result"]
    plan_info = result_dict["plan"]
    elapsed_ms = result_dict["elapsed_ms"]

    # ---- 输出 ----
    if json_output:
        import json
        render_json({
            "task": task_text,
            "plan": plan_info,
            "result": result_text,
            "elapsed_ms": elapsed_ms,
        })
    else:
        # 显示计划（如启用）
        if verbose and plan_info:
            render_info(
                f"[plan] intent={plan_info.get('intent','?')} "
                f"skills={plan_info.get('skills',[])} "
                f"workflow={plan_info.get('workflow') or 'none'}"
            )
            if plan_info.get("steps"):
                for s in plan_info["steps"]:
                    render_info(f"  step{s['order']}: {s['description']} [{s.get('skill','')}]")
            blank()

        blank()
        render_markdown(result_text)
        blank()
        dim(f"{elapsed_ms / 1000:.1f}s")

    # ---- 写入文件 ----
    if output:
        try:
            with open(output, "w", encoding="utf-8") as f:
                f.write(result_text)
            render_success(f"已写入: {output}")
        except OSError as exc:
            render_error(f"写入失败: {exc}")

    # ---- 清理 ----
    asyncio.run(svc.stop())


async def _init_service(model: str | None):
    """初始化 RuntimeService。"""
    from haven.cli.services.runtime_service import RuntimeService

    svc = RuntimeService()
    try:
        await svc.start(model=model, load_mcp=False)
        return svc
    except Exception as exc:
        render_error(f"启动 Runtime 失败: {exc}")
        raise typer.Exit(code=1)
