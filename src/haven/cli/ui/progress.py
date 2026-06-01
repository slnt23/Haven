"""加载动画 + 流式输出 + Workflow 节点观察。"""

from __future__ import annotations

from contextlib import asynccontextmanager
import sys

from rich.console import Console
from rich.live import Live
from rich.spinner import Spinner
from rich.text import Text

_console = Console(highlight=False)


@asynccontextmanager
async def spinner(message: str = "处理中"):
    """异步上下文管理器：显示旋转等待动画。"""
    text = Text(f"  {message}...", style="dim")
    with Live(Spinner("dots", text=text), console=_console, transient=True):
        yield


class StreamRenderer:
    """流式输出渲染器。逐 token 打印 LLM 输出。

    用法::

        renderer = StreamRenderer()
        async for token in llm_stream:
            renderer.feed(token)
        renderer.flush()
    """

    def __init__(self):
        self._buffer: list[str] = []
        self._line_start = True
        self._first_token = True

    def feed(self, token: str) -> None:
        if self._first_token:
            _console.print()
            self._first_token = False

        sys.stdout.write(token)
        sys.stdout.flush()
        self._buffer.append(token)
        if "\n" in token:
            self._line_start = True
        else:
            self._line_start = False

    def flush(self) -> str:
        sys.stdout.write("\n\n")
        sys.stdout.flush()
        result = "".join(self._buffer)
        self._buffer.clear()
        self._first_token = True
        return result


class NodeWatcher:
    """Workflow 节点实时观察器。

    用法::

        watcher = NodeWatcher(graph)
        watcher.update("planner", "done")
        watcher.update("coder", "running")
    """

    _STATUS_ICONS = {
        "pending": "[dim]○[/]",
        "running": "[cyan]◉[/]",
        "done": "[green]●[/]",
        "failed": "[red]✕[/]",
        "retrying": "[yellow]↻[/]",
    }

    def __init__(self, nodes: list[str]):
        self._nodes = nodes
        self._statuses: dict[str, str] = {n: "pending" for n in nodes}
        self._live: Live | None = None

    def start(self) -> None:
        self._live = Live(self._render(), console=_console, refresh_per_second=4)

    def update(self, node: str, status: str) -> None:
        if node in self._statuses:
            self._statuses[node] = status
        if self._live:
            self._live.update(self._render())

    def stop(self) -> None:
        if self._live:
            self._live.stop()

    def _render(self) -> Text:
        text = Text("\n  Workflow:\n")
        for node in self._nodes:
            icon = self._STATUS_ICONS.get(self._statuses[node], "?")
            text.append(f"    {icon} {node}\n")
        return text
