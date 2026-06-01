"""haven workflow — 工作流管理。调用 WorkflowRegistry 获取真实数据。"""

from __future__ import annotations

from typing import Annotated, Optional

import typer

from haven.cli.ui.console import (
    blank,
    dim,
    render_error,
    render_info,
    render_json,
    render_list,
    render_markdown,
    render_success,
    render_table,
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
            drawable = graph.get_graph()
            nodelist = list(drawable.nodes)
        except Exception:
            nodelist = []

        rows.append(
            {
                "Name": name,
                "Nodes": len(nodelist),
                "Flow": " → ".join(nodelist) if nodelist else "?",
            }
        )

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
        raise typer.Exit(code=1) from exc

    drawable = wf.get_graph()
    nodelist = list(drawable.nodes)
    edges_raw = list(drawable.edges)
    entry = nodelist[0] if nodelist else "?"
    edges_info: list[str] = [f"{s} → {t}" for s, t in edges_raw]

    if json_output:
        render_json(
            {
                "name": name,
                "entry": entry,
                "nodes": nodelist,
                "edges": edges_info,
            }
        )
    else:
        render_info(f"名称: {name}")
        render_info(f"入口: {entry}")
        render_info(f"节点 ({len(nodelist)}):")
        render_list(nodelist, bullet="○")
        blank()
        render_info("边:")
        render_list(edges_info, bullet="→")
        blank()

        if graph and nodelist:
            _render_ascii_graph(nodelist, edges_info)


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
    """按工作流执行任务。每个节点依次运行，支持失败重试。"""
    registry = _get_registry()
    if name not in registry.list_all():
        render_error(f"工作流不存在: {name}。可用: {', '.join(registry.list_all())}")
        raise typer.Exit(code=1)

    if not task.strip():
        render_error("--task 不能为空")
        raise typer.Exit(code=1)

    # ---- 获取 Graph 信息 ----
    try:
        graph = registry.build(name)
        drawable = graph.get_graph()
        nodes = list(drawable.nodes)
    except Exception as exc:
        render_error(f"构建工作流失败: {exc}")
        raise typer.Exit(code=1) from exc

    # ---- 初始化 RuntimeService ----
    import asyncio

    from haven.cli.services.runtime_service import RuntimeService

    async def _exec():
        svc = RuntimeService()
        await svc.start(session_id=f"wf_{name}", load_mcp=False)

        if watch:
            from haven.cli.ui.progress import NodeWatcher

            watcher = NodeWatcher(nodes)
            watcher.start()

        try:
            result = await svc.run_workflow(name, task, checkpoint=checkpoint)
        finally:
            if watch:
                watcher.stop()
            await svc.stop()

        return result

    result = asyncio.run(_exec())

    # ---- 输出 ----
    if json_output:
        render_json(result)
    else:
        blank()
        render_success(
            f"工作流: {name}  ({result['nodes_executed']} 个节点, {result['elapsed_ms']}ms)"
        )
        blank()
        render_markdown(result["result"])
        blank()

    if output:
        try:
            with open(output, "w", encoding="utf-8") as f:
                f.write(result["result"])
            render_success(f"结果已写入: {output}")
        except OSError as exc:
            render_error(f"写入失败: {exc}")


@workflow_app.command("resume", help="从 checkpoint 恢复执行")
def resume(
    ctx: typer.Context,
    session_id: Annotated[str, typer.Argument(help="Checkpoint thread ID")],
    watch: Annotated[bool, typer.Option("--watch", "-w", help="实时观察")] = False,
) -> None:
    """从上次中断的 checkpoint 恢复执行。"""
    try:
        from haven.workflows.graph import create_checkpointer

        cp = create_checkpointer()
        import asyncio

        state = asyncio.get_event_loop().run_until_complete(
            cp.aget_tuple({"configurable": {"thread_id": session_id}})
        )
        if state:
            render_success(f"已恢复 thread: {session_id}")
            checkpoint = state.config.get("configurable", {})
            render_info(f"  checkpoint_id: {checkpoint.get('checkpoint_id', '?')}")
        else:
            render_error(f"Checkpoint 不存在: {session_id}")
    except Exception as exc:
        render_error(str(exc))


@workflow_app.command("history", help="列出可恢复的执行")
def history(
    ctx: typer.Context,
    json_output: Annotated[bool, typer.Option("--json", "-j", help="JSON 输出")] = False,
) -> None:
    """列出所有可恢复的工作流执行。"""
    try:
        from haven.workflows.graph import create_checkpointer

        cp = create_checkpointer()
        import asyncio

        configs = asyncio.get_event_loop().run_until_complete(cp.alist())
    except Exception:
        configs = []

    if json_output:
        render_json([dict(c.get("configurable", {})) for c in configs])
    elif not configs:
        render_info("(无可用 checkpoint)")
    else:
        rows = [
            {
                "Thread": c.get("configurable", {}).get("thread_id", "?"),
                "Checkpoint": c.get("configurable", {}).get("checkpoint_id", "?")[:12],
            }
            for c in configs
        ]
        render_table(rows)
