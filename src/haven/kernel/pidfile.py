"""PID 文件管理 — 守护进程的单实例锁。

通过读写 PID 文件来控制守护进程的生命周期：
启动时写入、停止时删除、状态检测时检查进程存活。
跨平台兼容 Windows（tasklist）和 Unix（os.kill）。
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
import subprocess
import sys

logger = logging.getLogger("haven.pidfile")


def write(path: Path) -> None:
    """将当前进程 PID 写入 *path*，父目录不存在时自动创建。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(os.getpid()))
    logger.debug("PID %d written to %s", os.getpid(), path)


def read(path: Path) -> int | None:
    """从 *path* 读取 PID。文件缺失或内容无效时返回 ``None``。"""
    if not path.exists():
        return None
    try:
        return int(path.read_text().strip())
    except (ValueError, OSError):
        return None


def is_running(pid: int) -> bool:
    """检查 *pid* 对应的进程是否存活。

    Windows 下通过 ``tasklist`` 命令查询，Unix 下通过 ``os.kill(pid, 0)`` 检测。
    """
    if sys.platform == "win32":
        result = subprocess.run(
            ["tasklist", "/fi", f"PID eq {pid}", "/nh"],
            capture_output=True,
            text=True,
        )
        return str(pid) in result.stdout
    else:
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False


def remove(path: Path) -> None:
    """删除 *path* 处的 PID 文件，文件不存在时静默忽略。"""
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass
