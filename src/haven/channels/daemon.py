"""Haven 守护进程 —— 长期运行，通过飞书 WebSocket 共享单个 Runtime。

Runtime 包含 Coordinator（规划）+ Dispatcher（执行）+ Agents + Tools，
所有 Channel 共享同一个 Runtime 实例。
"""

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
from haven.channels.base_channel import BaseChannel
from haven.channels.feishu_channel import FeishuChannel

logger = logging.getLogger("haven.daemon")


def _daemon_banner() -> str:
    try:
        from haven import __version__ as ver
    except Exception:
        ver = "1.0.1"
    return f"""
  +--------------------------------------------------------------+
  |                    Haven Daemon v{ver}                       |
  |                                                              |
  |  Daemon is running. Press Ctrl+C to stop.                    |
  +--------------------------------------------------------------+
"""


class HavenDaemon:
    """长期运行守护进程，通过飞书 WebSocket 共享单个 Runtime。"""

    def __init__(self) -> None:
        self.runtime: Any = None
        self.channels: list[BaseChannel] = []
        self._running = False
        self._shutdown_event = asyncio.Event()

    async def start(self) -> None:
        """启动守护进程：初始化 Runtime → 构建 Channel → 注册信号。"""
        existing = pid_read(settings.pid_file)
        if existing is not None and is_running(existing):
            logger.error("Daemon already running (PID %d). Use 'haven stop' first.", existing)
            raise SystemExit(1)

        await self._init_runtime()
        self._build_channels()
        await self._start_channels()
        self._register_signals()
        pid_write(settings.pid_file)
        self._running = True
        self._print_status()

    async def stop(self) -> None:
        """停止守护进程：停止 Channel → 停止 ToolLoader → 清理 PID。"""
        if not self._running:
            return
        self._running = False

        logger.info("Shutting down channels...")
        for ch in self.channels:
            try:
                await ch.stop()
            except Exception as exc:
                logger.warning("Error stopping channel '%s': %s", ch.name, exc)

        if self.runtime:
            try:
                await self.runtime.close()
            except Exception as exc:
                logger.debug("Runtime close: %s", exc)

        pid_remove(settings.pid_file)
        logger.info("Haven daemon stopped")

    async def run_forever(self) -> None:
        """运行直到收到停止信号。"""
        try:
            await self.start()
            await self._shutdown_event.wait()
        finally:
            await self.stop()

    # ------------------------------------------------------------------
    # 内部实现
    # ------------------------------------------------------------------

    async def _init_runtime(self) -> None:
        """创建 Runtime（Coordinator + Dispatcher + Agents + Tools）。"""
        from haven.runtime.factory import create_runtime

        self.runtime = await create_runtime(
            session_id="daemon",
            entity_name="daemon_user",
            channel="daemon",
        )

    def _build_channels(self) -> None:
        """构建已启用的 Channel 列表。"""
        feishu_enabled = getattr(settings, "daemon_feishu_enabled", False)
        if feishu_enabled:
            self.channels.append(
                FeishuChannel(
                    app_id=getattr(settings, "daemon_feishu_app_id", ""),
                    app_secret=getattr(settings, "daemon_feishu_app_secret", ""),
                )
            )

    async def _start_channels(self) -> None:
        """启动所有 Channel，传入共享 Runtime。"""
        for ch in self.channels:
            try:
                await ch.start(self.runtime)
                logger.info("Channel '%s' started", ch.name)
            except Exception as exc:
                logger.error("Failed to start channel '%s': %s", ch.name, exc)

    def _register_signals(self) -> None:
        """注册 SIGINT/SIGTERM 信号处理。"""
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
        """打印守护进程启动状态。"""
        model = "unknown"
        if self.runtime:
            model = getattr(self.runtime.llm, "model_name", None) or "unknown"

        lines = [_daemon_banner(), f"  Model   : {model}", "  Channels:"]
        for ch in self.channels:
            detail = ch.status_detail
            label = f"  ({detail})" if detail else ""
            lines.append(f"    [OK] {ch.name}{label}")
        lines.append("")
        sys.stdout.write("\n".join(lines) + "\n")
        sys.stdout.flush()
