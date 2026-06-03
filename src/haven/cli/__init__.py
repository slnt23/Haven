"""Haven CLI V2 — Typer + Rich 命令体系。

haven              交互式 REPL（默认）
haven --task TEXT   单次任务（执行后退出）
haven status        查看守护进程状态
haven serve         启动守护进程
"""

from .main import app, main_cli

__all__ = ["app", "main_cli"]
