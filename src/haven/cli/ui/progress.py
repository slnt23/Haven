"""终端动态刷新渲染 — Live spinner + 原地状态更新 + 完整块输出。"""

from __future__ import annotations

import re
import time
from contextlib import asynccontextmanager

from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.spinner import Spinner
from rich.syntax import Syntax
from rich.text import Text

_console = Console(highlight=False)

# ---------------------------------------------------------------------------
# 异步 spinner（供 --task 模式使用）
# ---------------------------------------------------------------------------


@asynccontextmanager
async def spinner(message: str = "处理中"):
    """异步上下文管理器：显示旋转等待动画，任务完成后消失。"""
    text = Text(f"  {message}...", style="dim")
    with Live(Spinner("dots", text=text), console=_console, transient=True):
        yield


# ---------------------------------------------------------------------------
# DynamicRenderer — 原地动态刷新 + 完整块输出
# ---------------------------------------------------------------------------


class DynamicRenderer:
    """终端动态渲染器。

    类似网页局部刷新：在终端原地显示进度（spinner + 状态文字），
    后台收集 LLM 响应，最后一次性渲染完整结果（代码块高亮）。

    用法::

        renderer = DynamicRenderer()
        async with renderer:
            async for token in svc.chat_stream(user_input):
                renderer.feed(token)
        renderer.render()  # 输出最终结果
    """

    _CODE_FENCE = re.compile(r"^```")

    def __init__(self, status_text: str = "思考中"):
        self._status_text = status_text
        self._buffer: list[str] = []
        self._started_at: float = 0.0
        self._live: Live | None = None
        self._in_code_block = False
        self._line_count = 0

    # ---- 上下文管理器 ----

    async def __aenter__(self) -> "DynamicRenderer":
        self._started_at = time.monotonic()
        self._live = Live(
            self._make_panel(),
            console=_console,
            refresh_per_second=8,
            transient=True,
        )
        self._live.start()
        return self

    async def __aexit__(self, *_) -> None:
        if self._live:
            self._live.stop()
            self._live = None

    # ---- 数据输入 ----

    def feed(self, token: str) -> None:
        """接收 token，缓冲并更新状态提示。"""
        self._buffer.append(token)

        # 检测代码块边界以更新状态提示
        for line in token.split("\n"):
            if self._CODE_FENCE.match(line):
                if self._in_code_block:
                    self._status_text = "整理输出中"
                else:
                    self._status_text = "生成代码中"
                self._in_code_block = not self._in_code_block
            elif line.strip():
                self._line_count += 1

        # 刷新 Live 面板
        if self._live:
            self._live.update(self._make_panel())

    # ---- 最终渲染 ----

    def render(self) -> str:
        """停止 Live 并渲染完整响应（Markdown + 代码高亮 + Haven 面板）。"""
        if self._live:
            self._live.stop()
            self._live = None

        result = "".join(self._buffer)
        self._buffer.clear()
        self._in_code_block = False
        self._line_count = 0

        if not result.strip():
            return result

        # 捕获 Markdown+代码渲染 → 包装为 Haven 面板
        with _console.capture() as capture:
            _render_markdown_with_code(result)
        rendered = capture.get()

        _console.print()
        _console.print(Panel(rendered, title="Haven", border_style="blue", padding=(0, 1)))
        _console.print()
        return result

    # ---- 内部 ----

    def _make_panel(self) -> Panel:
        elapsed = time.monotonic() - self._started_at
        spinner_text = Text(f"  {self._status_text}...", style="bold cyan")
        spinner_text.append(f"  [{elapsed:.1f}s]", style="dim")

        detail = ""
        if self._line_count > 0:
            detail = f"\n  已生成 {self._line_count} 行"
        if self._in_code_block:
            detail += " | [cyan]代码块写入中[/]"

        content = Text()
        content.append(spinner_text)
        if detail:
            content.append(Text(detail, style="dim"))

        return Panel(content, border_style="blue", padding=(0, 1))


# ---------------------------------------------------------------------------
# Markdown 渲染（含代码语法高亮）
# ---------------------------------------------------------------------------

_CODE_BLOCK_RE = re.compile(r"```(\w+)?\n(.*?)```", re.DOTALL)


def _render_markdown_with_code(text: str) -> None:
    """渲染 Markdown 文本，代码块使用语法高亮。"""
    parts = _CODE_BLOCK_RE.split(text)
    # parts alternates: [text, lang, code, text, lang, code, ...]
    i = 0
    while i < len(parts):
        if i + 2 < len(parts):
            # Text before code block
            if parts[i].strip():
                _console.print(Markdown(parts[i]))
            # Code block
            lang = parts[i + 1] or "text"
            code = parts[i + 2]
            _console.print(Syntax(code.strip(), lang, theme="monokai", line_numbers=False))
            i += 3
        else:
            # Remaining text
            if parts[i].strip():
                _console.print(Markdown(parts[i]))
            i += 1
