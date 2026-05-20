from __future__ import annotations

import asyncio
import logging
import signal
import sys
from pathlib import Path

from forest.config import settings
from forest.core.base_agent import BaseAgent
from forest.skills.loader import SkillLoader
from forest.services.base_channel import BaseChannel
from forest.services.email_channel import EmailChannel
from forest.services.socket_channel import SocketChannel

logger = logging.getLogger("forest.daemon")

BANNER = """
  +--------------------------------------------------------------+
  |                    Haven Daemon v0.1.0                       |
  |                                                            |
  |  Daemon is running. Press Ctrl+C to stop.                  |
  +--------------------------------------------------------------+
"""


class HavenDaemon:
    """Long-running daemon that shares a single Agent across multiple channels.

    Channels (email, socket, future WeChat, ...) run as parallel asyncio
    tasks.  The agent is initialised once and shared.
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
        await self._init_agent()
        await self._init_mcp()
        self._build_channels()
        await self._start_channels()
        self._register_signals()
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
        from forest.agents import GeneralAgent

        self.agent = GeneralAgent()
        self.agent.memory.session_id = "daemon"
        self.agent.memory.entity_name = "daemon_user"
        self.agent.memory.channel = "daemon"
        if self.agent.llm is None:
            self.agent._init_llm()

        # load skills
        skill_dir = settings.project_root / settings.skill_directory
        if skill_dir.is_dir():
            loaded = SkillLoader.load_from_dir(skill_dir)
            for skill in loaded:
                self.agent.skills[skill.name] = skill
        logger.info("Agent initialised, %d skill(s) loaded", len(self.agent.skills))

    async def _init_mcp(self) -> None:
        if not settings.mcp_enabled or self.agent is None:
            return

        try:
            from forest.mcp import MCPManager, MCPServerConfig
            from forest.config import get_mcp_config
        except ImportError as exc:
            logger.warning("MCP SDK not available, skipping (%s)", exc)
            return

        raw_configs = get_mcp_config()
        if not raw_configs:
            return

        configs = []
        for raw in raw_configs:
            try:
                configs.append(MCPServerConfig(**raw))
            except Exception as exc:
                logger.warning("Invalid MCP config, skipping: %s", exc)
                continue

        configs = [c for c in configs if c.enabled]
        if not configs:
            return

        self.agent.mcp_manager = MCPManager(configs)
        try:
            mcp_tools = await self.agent.mcp_manager.start()
        except Exception as exc:
            logger.warning("MCP connection failed: %s", exc)
            self.agent.mcp_manager = None
            return

        if mcp_tools:
            self.agent.register_mcp_tools(mcp_tools)
            self.agent.bind_tools_to_llm()
            logger.info("MCP: %d tool(s) loaded", len(mcp_tools))

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
                    signal.signal(sig, lambda s, f: self._shutdown_event.set())
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
            detail = ""
            if ch.name == "socket":
                host = getattr(ch, "host", "?")
                port = getattr(ch, "port", "?")
                detail = f"  (tcp://{host}:{port})"
            lines.append(f"    [OK] {ch.name}{detail}")
        lines.append("")
        sys.stdout.write("\n".join(lines) + "\n")
        sys.stdout.flush()
