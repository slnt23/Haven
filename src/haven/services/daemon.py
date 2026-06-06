from __future__ import annotations

import asyncio
import logging
import signal
import sys
from typing import Any

from haven.config import settings
from haven.core.pidfile import is_running
from haven.core.pidfile import read as pid_read
from haven.core.pidfile import remove as pid_remove
from haven.core.pidfile import write as pid_write
from haven.services.base_channel import BaseChannel
from haven.services.feishu_channel import FeishuChannel

logger = logging.getLogger("haven.daemon")

BANNER = """
  +--------------------------------------------------------------+
  |                    Haven Daemon v2.0.0                       |
  |                                                              |
  |  Daemon is running. Press Ctrl+C to stop.                    |
  +--------------------------------------------------------------+
"""


class HavenDaemon:
    """长期运行守护进程，通过飞书 WebSocket 共享单个 Coordinator。"""

    def __init__(self) -> None:
        self.agent: Any = None
        self.channels: list[BaseChannel] = []
        self._running = False
        self._shutdown_event = asyncio.Event()

    async def start(self) -> None:
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
        if not self._running:
            return
        self._running = False

        logger.info("Shutting down channels...")
        for ch in self.channels:
            try:
                await ch.stop()
            except Exception as exc:
                logger.warning("Error stopping channel '%s': %s", ch.name, exc)

        if self.agent:
            tm = getattr(self.agent, "tool_manager", None)
            if tm:
                try:
                    await tm.stop_all()
                except Exception as exc:
                    logger.debug("ToolManager shutdown: %s", exc)
            # checkpointer 自动持久化

        pid_remove(settings.pid_file)
        logger.info("Haven daemon stopped")

    async def run_forever(self) -> None:
        try:
            await self.start()
            await self._shutdown_event.wait()
        finally:
            await self.stop()

    # ------------------------------------------------------------------
    # 内部实现
    # ------------------------------------------------------------------

    async def _init_agent(self) -> None:
        from haven.runtime.factory import create_coordinator

        self.agent = await create_coordinator(
            session_id="daemon",
            entity_name="daemon_user",
            channel="daemon",
        )

    def _build_channels(self) -> None:
        feishu_enabled = getattr(settings, "daemon_feishu_enabled", False)
        if feishu_enabled:
            self.channels.append(
                FeishuChannel(
                    app_id=getattr(settings, "daemon_feishu_app_id", ""),
                    app_secret=getattr(settings, "daemon_feishu_app_secret", ""),
                )
            )

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
                try:
                    signal.signal(sig, lambda *_: self._shutdown_event.set())
                except Exception:
                    pass

    def _print_status(self) -> None:
        rt = self.agent.runtime if self.agent else None
        llm = getattr(rt, "llm", None) if rt else None
        model = getattr(llm, "model_name", None) or "unknown"

        lines = [BANNER, f"  Model   : {model}", "  Channels:"]
        for ch in self.channels:
            detail = ch.status_detail
            label = f"  ({detail})" if detail else ""
            lines.append(f"    [OK] {ch.name}{label}")
        lines.append("")
        sys.stdout.write("\n".join(lines) + "\n")
        sys.stdout.flush()
