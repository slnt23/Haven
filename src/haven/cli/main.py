"""``haven`` CLI 命令入口。"""

from __future__ import annotations

import asyncio
import logging
import sys

from haven.config import settings
from haven.core.pidfile import is_running, kill, read as pid_read, remove as pid_remove


def main() -> None:
    """运行 Haven REPL、单轮查询、守护进程或管理命令。

    用法::

        haven                  # 交互式 REPL
        haven --task <prompt>  # 单轮查询
        haven serve            # 启动守护进程（常驻、多通道）
        haven stop             # 停止运行中的守护进程
        haven status           # 查看守护进程状态
        haven restart          # 重启守护进程
    """
    args = sys.argv[1:]

    # 管理命令（stop / status / restart）
    if args and args[0] in _MANAGEMENT_COMMANDS:
        _MANAGEMENT_COMMANDS[args[0]]()
        return

    # 守护进程模式
    if args and args[0] == "serve":
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%H:%M:%S",
        )
        asyncio.run(_run_daemon())
        return

    # 单轮模式：haven --task "你的问题"
    task: str | None = None
    if args and args[0] == "--task":
        if len(args) > 1:
            task = " ".join(args[1:])

    from haven.cli.app import HavenApp

    app = HavenApp()
    try:
        asyncio.run(app.start(greeting_task=task))
    except KeyboardInterrupt:
        pass


def _cmd_stop() -> None:
    """停止运行中的 Haven 守护进程。"""
    pid = pid_read(settings.pid_file)
    if pid is None:
        print("Haven daemon is not running (no PID file).")
        return
    if not is_running(pid):
        print(f"PID file found but process {pid} is not alive. Cleaning up.")
        pid_remove(settings.pid_file)
        return
    print(f"Stopping Haven daemon (PID {pid})...")
    kill(pid)
    pid_remove(settings.pid_file)
    print("Done.")


def _cmd_status() -> None:
    """打印 Haven 守护进程状态。"""
    pid = pid_read(settings.pid_file)
    if pid is None:
        print("Haven daemon is not running.")
        return
    if is_running(pid):
        print(f"Haven daemon is running (PID {pid}).")
    else:
        print(f"PID file found but process {pid} is not alive. Cleaning up.")
        pid_remove(settings.pid_file)


def _cmd_restart() -> None:
    """停止运行中的守护进程（如有）并启动新的。"""
    _cmd_stop()
    print("Starting Haven daemon...")
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    asyncio.run(_run_daemon())


_MANAGEMENT_COMMANDS = {
    "stop": _cmd_stop,
    "status": _cmd_status,
    "restart": _cmd_restart,
}


async def _run_daemon() -> None:
    from haven.services.daemon import HavenDaemon

    daemon = HavenDaemon()
    try:
        await daemon.run_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
