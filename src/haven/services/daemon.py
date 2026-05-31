from __future__ import annotations

import asyncio
import logging
import signal
import sys

from haven.config import settings
from haven.core.base_agent import BaseAgent
from haven.core.pidfile import is_running, read as pid_read, remove as pid_remove, write as pid_write
from haven.services.base_channel import BaseChannel
from haven.services.email_channel import EmailChannel
from haven.services.feishu_channel import FeishuChannel
from haven.services.socket_channel import SocketChannel

logger = logging.getLogger("haven.daemon")

BANNER = """
  +--------------------------------------------------------------+
  |                    Haven Daemon v0.1.0                       |
  |                                                              |
  |  Daemon is running. Press Ctrl+C to stop.                    |
  +--------------------------------------------------------------+
"""


class HavenDaemon:
    """Long-running daemon that shares a single Agent across multiple channels.

    Channels (socket, email, feishu, ...) run as parallel asyncio tasks.
    The agent is initialised once and shared.
    """

    def __init__(self) -> None:
        self.agent: BaseAgent | None = None
        self.channels: list[BaseChannel] = []
        self._running = False
        self._shutdown_event = asyncio.Event()

    # ------------------------------------------------------------------
    # lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Initialise agent and start all enabled channels."""
        existing = pid_read(settings.pid_file)
        if existing is not None and is_running(existing):
            logger.error("Daemon already running (PID %d). Use 'haven stop' first.", existing)
            raise SystemExit(1)

        await self._init_agent()
        self._build_channels()
        await self._start_channels()
        self._register_signals()
        pid_write(settings.pid_file)
        self._running = True
        self._print_status()

    async def stop(self) -> None:
        """Gracefully stop all channels and release resources."""
        if not self._running:
            return
        self._running = False

        logger.info("Shutting down channels...")
        for ch in self.channels:
            try:
                await ch.stop()
            except Exception as exc:
                logger.warning("Error stopping channel '%s': %s", ch.name, exc)

        if self.agent and hasattr(self.agent, "mcp_manager") and self.agent.mcp_manager:
            try:
                await self.agent.mcp_manager.stop()
            except Exception as exc:
                logger.debug("MCP shutdown: %s", exc)

        pid_remove(settings.pid_file)
        logger.info("Haven daemon stopped")

    async def run_forever(self) -> None:
        """Start daemon and wait for shutdown signal.

        Shuts down cleanly on Ctrl+C (SIGINT) or SIGTERM.
        """
        try:
            await self.start()
            await self._shutdown_event.wait()
        finally:
            await self.stop()

    # ------------------------------------------------------------------
    # internal
    # ------------------------------------------------------------------

    async def _init_agent(self) -> None:
        from haven.agents.factory import create_agent

        self.agent = await create_agent(
            session_id="daemon",
            entity_name="daemon_user",
            channel="daemon",
        )
        logger.info("Agent initialised, %d skill(s) loaded", len(self.agent.skills))

    def _build_channels(self) -> None:
        # Socket channel
        socket_enabled = getattr(settings, "daemon_socket_enabled", True)
        socket_host = getattr(settings, "daemon_socket_host", "127.0.0.1")
        socket_port = getattr(settings, "daemon_socket_port", 9020)
        if socket_enabled:
            self.channels.append(SocketChannel(
                host=socket_host, port=socket_port,
                shutdown_callback=self._shutdown_event.set,
            ))

        # Email channel
        email_enabled = getattr(settings, "daemon_email_enabled", False)
        if email_enabled:
            self.channels.append(EmailChannel())

        # Feishu channel
        feishu_enabled = getattr(settings, "daemon_feishu_enabled", False)
        if feishu_enabled:
            self.channels.append(FeishuChannel(
                app_id=getattr(settings, "daemon_feishu_app_id", ""),
                app_secret=getattr(settings, "daemon_feishu_app_secret", ""),
            ))

    async def _start_channels(self) -> None:
        for ch in self.channels:
            try:
                await ch.start(self.agent)
                logger.info("Channel '%s' started", ch.name)
            except Exception as exc:
                logger.error("Failed to start channel '%s': %s", ch.name, exc)

    def _register_signals(self) -> None:
        loop = asyncio.get_running_loop()

        def _handler() -> None:
            logger.info("Shutdown signal received")
            self._shutdown_event.set()

        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, _handler)
            except NotImplementedError:
                # Windows fallback: use signal.signal()
                try:
                    signal.signal(sig, lambda *_: self._shutdown_event.set())
                except Exception:
                    pass

    def _print_status(self) -> None:
        model = getattr(self.agent.llm, "model_name", None) or "unknown"
        lines = [
            BANNER,
            f"  Model   : {model}",
            f"  Skills  : {len(self.agent.skills) if self.agent else 0}",
            f"  Channels:",
        ]
        for ch in self.channels:
            detail = ch.status_detail
            label = f"  ({detail})" if detail else ""
            lines.append(f"    [OK] {ch.name}{label}")
        lines.append("")
        sys.stdout.write("\n".join(lines) + "\n")
        sys.stdout.flush()
