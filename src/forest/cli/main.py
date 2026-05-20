"""Entry point for the ``haven`` CLI command."""

from __future__ import annotations

import asyncio
import logging
import sys


def main() -> None:
    """Run the Haven REPL, one-shot query, or daemon.

    Usage::

        haven                  # Interactive REPL
        haven --task <prompt>  # One-shot query
        haven serve            # Start daemon (persistent, multi-channel)
    """
    args = sys.argv[1:]

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


async def _run_daemon() -> None:
    from forest.services.daemon import HavenDaemon

    daemon = HavenDaemon()
    try:
        await daemon.run_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
