"""Entry point for the ``haven`` CLI command."""

from __future__ import annotations

import asyncio
import sys


def main() -> None:
    """Run the Haven REPL.  Use ``haven --task <prompt>`` for a one-shot query."""
    args = sys.argv[1:]

    # one-shot mode: haven --task "your prompt"
    task: str | None = None
    if args and args[0] == "--task":
        if len(args) > 1:
            task = " ".join(args[1:])
        else:
            task = " ".join(args[1:]) if len(args) > 1 else None

    from forest.cli.app import HavenApp

    app = HavenApp()
    try:
        asyncio.run(app.start(greeting_task=task))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
