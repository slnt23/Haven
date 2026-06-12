"""Haven CLI — 多智能体交互框架入口。"""

import asyncio
import logging
import sys
from pathlib import Path
import warnings

from haven.interface.cli.repl import run_repl

_LOG_FMT = "[%(name)s] %(levelname)s: %(message)s"


def _setup_logging() -> None:
    """配置双通道日志：文件 (INFO+) + 控制台 (WARNING+)。

    控制台只显示 WARNING 和 ERROR，保持终端界面干净。
    完整日志写入 logs/runtime.log。
    """
    root = logging.getLogger()
    root.setLevel(logging.INFO)

    # 清除已有的 handler
    root.handlers.clear()

    # FileHandler — 记录所有 INFO 及以上日志
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)
    fh = logging.FileHandler(
        log_dir / "runtime.log", encoding="utf-8", mode="a",
    )
    fh.setLevel(logging.INFO)
    fh.setFormatter(logging.Formatter(_LOG_FMT))
    root.addHandler(fh)

    # ConsoleHandler — 仅显示 WARNING 及以上
    ch = logging.StreamHandler(sys.stderr)
    ch.setLevel(logging.WARNING)
    ch.setFormatter(logging.Formatter(_LOG_FMT))
    root.addHandler(ch)


def main_cli() -> None:
    """入口：直接进入 REPL 对话。"""
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8", errors="replace")

    _setup_logging()

    warnings.filterwarnings("ignore", module="langgraph")

    try:
        asyncio.run(run_repl())
    except KeyboardInterrupt:
        pass
    finally:
        print("\n再会，愿灯塔照亮前路。", file=sys.stderr)
