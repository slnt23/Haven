"""统一终端输出。Rich Console 包装。

支持: table / json / kv-list / status-line / markdown。
全局单例 ``console``，按 ``--output-format`` 自动切换渲染模式。
"""

from __future__ import annotations

import json as json_mod
from typing import Any

from rich.console import Console as RichConsole
from rich.markdown import Markdown
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table
from rich.tree import Tree

_console = RichConsole(highlight=False)


def get_console() -> RichConsole:
    return _console


# ====================================================================
# 渲染函数
# ====================================================================


def render_table(
    rows: list[dict[str, Any]] | list[list],
    *,
    headers: list[str] | None = None,
    title: str | None = None,
) -> None:
    """渲染表格。rows 为 dict 列表时自动取 key 为列名。"""
    if not rows:
        _console.print("[dim](empty)[/dim]")
        return

    if isinstance(rows[0], dict):
        headers = headers or list(rows[0].keys())
        table = Table(title=title)
        for h in headers:
            table.add_column(h, style="cyan")
        for row in rows:
            table.add_row(*[str(row.get(h, "")) for h in headers])
    else:
        headers = headers or [f"Col{i}" for i in range(len(rows[0]))]
        table = Table(title=title)
        for h in headers:
            table.add_column(h, style="cyan")
        for row in rows:
            table.add_row(*[str(c) for c in row])
    _console.print(table)


def render_json(data: Any) -> None:
    _console.print_json(json_mod.dumps(data, ensure_ascii=False, indent=2, default=str))


def render_kv(pairs: dict[str, Any] | list[tuple[str, Any]], *, title: str | None = None) -> None:
    """渲染键值对列表。"""
    if isinstance(pairs, dict):
        items = list(pairs.items())
    else:
        items = pairs

    table = Table(title=title, show_header=False, box=None, padding=(0, 1))
    table.add_column("key", style="green")
    table.add_column("value", style="white")
    for k, v in items:
        table.add_row(str(k), str(v))
    _console.print(table)


def render_status(icon: str, message: str, *, style: str = "white") -> None:
    """渲染单行状态: [icon] message。"""
    _console.print(f"  {icon} {message}", style=style)


def render_error(message: str) -> None:
    _console.print(f"\n[bold red]Error:[/] {message}\n")


def render_warning(message: str) -> None:
    _console.print(f"[yellow]Warning:[/] {message}")


def render_info(message: str) -> None:
    _console.print(f"[dim]{message}[/]")


def render_success(message: str) -> None:
    _console.print(f"[green]{message}[/]")


def render_markdown(text: str) -> None:
    _console.print(Markdown(text))


def render_code(code: str, language: str = "python") -> None:
    _console.print(Syntax(code, language, theme="monokai", line_numbers=False))


def render_panel(content: str, *, title: str = "", style: str = "blue") -> None:
    _console.print(Panel(content, title=title, border_style=style))


# ====================================================================
# 消息装饰 — 用户输入 / AI 回复
# ====================================================================


def render_user_message(text: str) -> None:
    """回显用户输入，dim 边框 + You 标签。"""
    _console.print()
    _console.print(Panel(text.strip(), title="You", border_style="dim", padding=(0, 1)))
    _console.print()


def render_assistant_message(text: str) -> None:
    """渲染 AI 回复，蓝色边框 + Haven 标签。text 为 Rich 渲染后的字符串。"""
    _console.print(Panel(text, title="Haven", border_style="blue", padding=(0, 1)))
    _console.print()


def render_list(items: list[str], *, style: str = "white", bullet: str = "•") -> None:
    for item in items:
        _console.print(f"  {bullet} {item}", style=style)


def render_tree(data: dict[str, Any], *, title: str | None = None) -> None:
    """渲染嵌套字典为树。"""
    tree = Tree(title or ".")

    def _build(parent: Tree, d: dict[str, Any]) -> None:
        for k, v in d.items():
            if isinstance(v, dict):
                branch = parent.add(f"[cyan]{k}[/]")
                _build(branch, v)
            elif isinstance(v, list):
                branch = parent.add(f"[cyan]{k}[/]")
                for item in v:
                    branch.add(str(item))
            else:
                parent.add(f"[green]{k}:[/] {v}")

    _build(tree, data)
    _console.print(tree)


# ====================================================================
# 便捷输出
# ====================================================================


def rule(title: str = "") -> None:
    _console.rule(title)


def blank() -> None:
    _console.print("")


def dim(text: str) -> None:
    _console.print(f"[dim]{text}[/]")


def bold(text: str) -> None:
    _console.print(f"[bold]{text}[/]")
