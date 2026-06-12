"""Haven CLI — 多智能体交互框架入口。"""

import asyncio
import logging
import sys
import warnings

from haven.interface.cli.repl import run_repl


def main_cli() -> None:
    """入口：直接进入 REPL 对话。"""
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8", errors="replace")

    logging.basicConfig(
        level=logging.INFO,
        format="[%(name)s] %(levelname)s: %(message)s",
        stream=sys.stderr,
    )

    warnings.filterwarnings("ignore", module="langgraph")

    try:
        asyncio.run(run_repl())
    except KeyboardInterrupt:
        pass
    finally:
        print("\n再会，愿灯塔照亮前路。", file=sys.stderr)
