"""haven tool — 工具查询。使用 ToolManager 真实数据。"""

from __future__ import annotations

from typing import Annotated

import typer

from haven.cli.ui.console import (
    render_table, render_json, render_error, render_info, dim, blank, render_kv,
)

tool_app = typer.Typer(help="工具查询")


def _get_tool_manager():
    """获取 ToolManager（Standalone: 仅加载 BuiltinProvider）。"""
    import asyncio
    from haven.tools.manager import ToolManager
    from haven.tools.providers.builtin import BuiltinProvider

    tm = ToolManager()
    tm.add_provider(BuiltinProvider())
    asyncio.run(tm.start_all())
    return tm


@tool_app.command("list", help="列出所有工具")
def list_tools(
    ctx: typer.Context,
    provider: Annotated[str | None, typer.Option("--provider", help="按 provider 过滤")] = None,
    category: Annotated[str | None, typer.Option("--category", help="按类别过滤")] = None,
    json_output: Annotated[bool, typer.Option("--json", "-j", help="JSON 输出")] = False,
) -> None:
    """列出已注册的工具。"""
    tm = _get_tool_manager()
    tools = tm.filter_tools(category=category, provider=provider) if (provider or category) else tm.list_all()

    if json_output:
        render_json([{"name": t.name, "provider": tm._tool_to_provider.get(t.name, "?"),
                       "description": getattr(t, "description", "")} for t in tools])
    elif not tools:
        render_info("(未加载任何工具)")
    else:
        rows = [{"Name": t.name, "Provider": tm._tool_to_provider.get(t.name, "?"),
                  "Description": (getattr(t, "description", "") or "")[:60]}
                 for t in sorted(tools, key=lambda x: x.name)]
        render_table(rows, headers=["Name", "Provider", "Description"])
        blank()
        dim(f"共 {len(tools)} 个工具  (来自 {len(tm.list_providers())} 个 provider)")


@tool_app.command("info", help="查看工具详情")
def info(
    ctx: typer.Context,
    name: Annotated[str, typer.Argument(help="工具名")],
    json_output: Annotated[bool, typer.Option("--json", "-j", help="JSON 输出")] = False,
) -> None:
    """查看指定工具的详细信息。"""
    tm = _get_tool_manager()
    tool = tm.get_tool(name)
    if tool is None:
        render_error(f"工具不存在: {name}。可用: {', '.join(tm.list_names())}")
        raise typer.Exit(code=1)

    if json_output:
        render_json({"name": tool.name, "description": getattr(tool, "description", ""),
                      "provider": tm._tool_to_provider.get(tool.name, "?")})
    else:
        render_kv([
            ("名称", tool.name),
            ("描述", getattr(tool, "description", "") or "(无)"),
            ("Provider", tm._tool_to_provider.get(tool.name, "?")),
        ])
