"""Haven CLI V2 — Typer + Rich 命令体系。

haven chat         交互式 REPL
haven run          单轮任务
haven workflow     工作流管理
haven skill        Skill 管理
haven doctor       环境诊断
"""

from .main import app, main_cli

__all__ = ["app", "main_cli"]
