"""haven workflow — 工作流管理。调用 WorkflowRegistry 获取真实数据。"""

from __future__ import annotations

from typing import Annotated, Optional

import typer

from haven.cli.ui.console import (
    get_console, render_table, render_json, render_error,
    render_success, render_info, render_list, dim, blank,
)

workflow_app = typer.Typer(help="工作流管理 + 执行")


def _get_registry():
    from haven.workflows.registry import WorkflowRegistry
    return WorkflowRegistry


@workflow_app.command("list", help="列出所有工作流")
def list_workflows(
    ctx: typer.Context,
    json_output: Annotated[bool, typer.Option("--json", "-j", help="JSON 输出")] = False,
) -> None:
    """列出所有已注册的工作流。"""
    registry = _get_registry()
    names = registry.list_all()

    if not names:
        if json_output:
            render_json([])
        else:
            render_info("(无可用工作流 — 导入 workflows 模块后自动注册)")
        return

    rows: list[dict] = []
    for name in sorted(names):
        try:
            graph = registry.build(name)
            nodes = list(graph._nodes.keys())
        except Exception:
            graph = None
            nodes = []

        rows.append({
            "Name": name,
            "Nodes": len(nodes),
            "Flow": " → ".join(nodes) if nodes else "?",
        })

    if json_output:
        render_json([{"name": r["Name"], "nodes": r["Nodes"], "flow": r["Flow"]} for r in rows])
    else:
        render_table(rows, headers=["Name", "Nodes", "Flow"])
        blank()
        dim(f"共 {len(rows)} 个工作流")


@workflow_app.command("info", help="查看工作流详情")
def info(
    ctx: typer.Context,
    name: Annotated[str, typer.Argument(help="工作流名")],
    graph: Annotated[bool, typer.Option("--graph", help="显示 DAG 图")] = False,
    json_output: Annotated[bool, typer.Option("--json", "-j", help="JSON 输出")] = False,
) -> None:
    """查看指定工作流的详细信息。"""
    registry = _get_registry()

    if name not in registry.list_all():
        render_error(f"工作流不存在: {name}。可用: {', '.join(registry.list_all())}")
        raise typer.Exit(code=1)

    try:
        wf = registry.build(name)
    except Exception as exc:
        render_error(f"构建工作流失败: {exc}")
        raise typer.Exit(code=1)

    nodes = list(wf._nodes.keys())
    entry = wf._entry_point
    edges_info: list[str] = []
    for src, edge in wf._edges.items():
        if hasattr(edge, "target"):
            edges_info.append(f"{src} → {edge.target}")
        else:
            edges_info.append(f"{src} → [router]")

    if json_output:
        render_json({
            "name": name, "entry": entry, "nodes": nodes, "edges": edges_info,
        })
    else:
        render_info(f"名称: {name}")
        render_info(f"入口: {entry}")
        render_info(f"节点 ({len(nodes)}):")
        render_list(nodes, bullet="○")
        blank()
        render_info("边:")
        render_list(edges_info, bullet="→")
        blank()

        if graph and nodes:
            _render_ascii_graph(nodes, edges_info)


def _render_ascii_graph(nodes: list[str], edges: list[str]) -> None:
    from haven.cli.ui.console import render_info
    lines = ["  " + " → ".join(nodes)]
    for e in edges:
        if "router" in e:
            lines.append(f"  ({e})")
    render_info("\n".join(lines))


@workflow_app.command("run", help="运行工作流")
def run_workflow(
    ctx: typer.Context,
    name: Annotated[str, typer.Argument(help="工作流名")],
    task: Annotated[str, typer.Option("--task", "-t", help="任务文本（必填）")] = "",
    watch: Annotated[bool, typer.Option("--watch", "-w", help="实时观察节点执行")] = False,
    stream: Annotated[bool, typer.Option("--stream", help="流式输出")] = False,
    json_output: Annotated[bool, typer.Option("--json", "-j", help="JSON 输出")] = False,
    output: Annotated[Optional[str], typer.Option("--output", "-o", help="结果写入文件")] = None,
    checkpoint: Annotated[bool, typer.Option("--checkpoint", help="启用 checkpoint")] = False,
) -> None:
    """按工作流执行任务。"""
    registry = _get_registry()
    if name not in registry.list_all():
        render_error(f"工作流不存在: {name}。可用: {', '.join(registry.list_all())}")
        raise typer.Exit(code=1)

    if not task.strip():
        render_error("--task 不能为空")
        raise typer.Exit(code=1)

    render_info(f"[TODO] 执行工作流 '{name}' — RuntimeService 集成后可用")
    render_info(f"  任务: {task[:80]}...")


@workflow_app.command("resume", help="从 checkpoint 恢复执行")
def resume(
    ctx: typer.Context,
    session_id: Annotated[str, typer.Argument(help="Checkpoint session ID")],
    watch: Annotated[bool, typer.Option("--watch", "-w", help="实时观察")] = False,
) -> None:
    """从上次中断的 checkpoint 恢复执行。"""
    try:
        from haven.workflows.checkpoint import SQLiteCheckpointer
        cp = SQLiteCheckpointer()
        import asyncio
        state = asyncio.get_event_loop().run_until_complete(cp.load(session_id))
        if state:
            render_success(f"已恢复 session: {session_id}")
            render_info(f"  当前节点: {state.get('current_node', '?')}")
        else:
            render_error(f"Session 不存在: {session_id}")
    except Exception as exc:
        render_error(str(exc))


@workflow_app.command("history", help="列出可恢复的执行")
def history(
    ctx: typer.Context,
    json_output: Annotated[bool, typer.Option("--json", "-j", help="JSON 输出")] = False,
) -> None:
    """列出所有可恢复的工作流执行。"""
    try:
        from haven.workflows.checkpoint import SQLiteCheckpointer
        cp = SQLiteCheckpointer()
        import asyncio
        sessions = asyncio.get_event_loop().run_until_complete(cp.list_sessions())
    except Exception:
        sessions = []

    if json_output:
        render_json(sessions)
    elif not sessions:
        render_info("(无可用 checkpoint)")
    else:
        rows = [{"Session": s.get("session_id", "?"), "Node": s.get("node_name", "?"),
                  "Time": s.get("created_at", "?")} for s in sessions]
        render_table(rows)
