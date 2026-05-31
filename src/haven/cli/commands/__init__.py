"""CLI V2 命令模块。

直接命令（注册在 main.py）:
  chat, run, doctor

子命令组（add_typer）:
  workflow, skill

扩展方式:
  1. 创建 commands/<name>.py
  2. 在 main.py 中注册
"""

from haven.cli.commands import chat, run, doctor, workflow, skill

__all__ = ["chat", "run", "doctor", "workflow", "skill"]
