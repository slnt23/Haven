from __future__ import annotations

import logging
import os
import signal
import subprocess
import sys
from pathlib import Path

logger = logging.getLogger("haven.pidfile")


def write(path: Path) -> None:
    """将当前进程 PID 写入 *path*。"""
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
    """检查 *pid* 对应的进程是否存活。"""
    if sys.platform == "win32":
        result = subprocess.run(
            ["tasklist", "/fi", f"PID eq {pid}", "/nh"],
            capture_output=True, text=True,
        )
        return str(pid) in result.stdout
    else:
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False


def remove(path: Path) -> None:
    """删除 *path* 处的 PID 文件。"""
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


