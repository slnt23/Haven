"""Entry point for the ``haven`` CLI command."""

from __future__ import annotations

import asyncio
import logging
import sys

from forest.config import settings
from forest.core.pidfile import is_running, kill, read as pid_read, remove as pid_remove


def main() -> None:
    """Run the Haven REPL, query, daemon, or management commands.

    Usage::

        haven                  # Interactive REPL
        haven --task <prompt>  # One-shot query
        haven serve            # Start daemon (persistent, multi-channel)
        haven stop             # Stop the running daemon
        haven status           # Show daemon status
        haven restart          # Restart the daemon
    """
    args = sys.argv[1:]

    # management commands (stop / status / restart)
    if args and args[0] in _MANAGEMENT_COMMANDS:
        _MANAGEMENT_COMMANDS[args[0]]()
        return

    # daemon mode
    if args and args[0] == "serve":
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%H:%M:%S",
        )
        asyncio.run(_run_daemon())
        return

    # one-shot mode: haven --task "your prompt"
    task: str | None = None
    if args and args[0] == "--task":
        if len(args) > 1:
            task = " ".join(args[1:])

    from forest.cli.app import HavenApp

    app = HavenApp()
    try:
        asyncio.run(app.start(greeting_task=task))
    except KeyboardInterrupt:
        pass


def _cmd_stop() -> None:
    """Stop the running Haven daemon."""
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
    """Print the status of the Haven daemon."""
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
    """Stop the running daemon (if any) and start a new one."""
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
    from forest.services.daemon import HavenDaemon

    daemon = HavenDaemon()
    try:
        await daemon.run_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
