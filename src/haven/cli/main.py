"""Haven CLI — 多智能体交互框架."""

import asyncio
import logging
import sys
import warnings

from haven.cli.repl import run_repl


def main_cli() -> None:
    """入口：直接进入 REPL 对话。"""
    # 确保标准输出使用 UTF-8，避免 emoji 等字符编码崩溃
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8", errors="replace")

    # 配置日志：输出到 stderr，INFO 级别，方便观察运行时状态
    logging.basicConfig(
        level=logging.INFO,
        format="[%(name)s] %(levelname)s: %(message)s",
        stream=sys.stderr,
    )

    # 屏蔽 LangGraph 内部的类型标注警告，不影响功能
    warnings.filterwarnings("ignore", module="langgraph")

    try:
        asyncio.run(run_repl())
    except KeyboardInterrupt:
        pass
    finally:
        print("\n再会，愿灯塔照亮前路。", file=sys.stderr)
