from __future__ import annotations

import logging
import os
import signal
import subprocess
import sys
from pathlib import Path

logger = logging.getLogger("forest.pidfile")


def write(path: Path) -> None:
    """Write the current process PID to *path*."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(os.getpid()))
    logger.debug("PID %d written to %s", os.getpid(), path)


def read(path: Path) -> int | None:
    """Read a PID from *path*.  Returns ``None`` when the file is missing
    or contains garbage."""
    if not path.exists():
        return None
    try:
        return int(path.read_text().strip())
    except (ValueError, OSError):
        return None


def is_running(pid: int) -> bool:
    """Check whether a process with *pid* is alive."""
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
    """Delete the PID file at *path*."""
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def kill(pid: int) -> None:
    """Terminate a process by *pid*."""
    if sys.platform == "win32":
        subprocess.run(["taskkill", "/f", "/pid", str(pid)], capture_output=True)
    else:
        os.kill(pid, signal.SIGTERM)
