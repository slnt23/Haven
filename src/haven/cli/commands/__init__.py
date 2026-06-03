"""CLI V2 命令模块。

直接命令（注册在 main.py）:
  status, serve

默认行为:
  haven → 交互式 REPL (chat.py)
"""

from haven.cli.commands import chat

__all__ = ["chat"]
