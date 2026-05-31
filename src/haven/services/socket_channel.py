from __future__ import annotations

import asyncio
import logging
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage

from haven.config import settings
from haven.core.base_agent import BaseAgent
from haven.core.session import ChatSession
from haven.services.base_channel import BaseChannel

logger = logging.getLogger("haven.socket_channel")

BANNER = (
    "\r\n"
    "  Haven · Multi-Agent Runtime\r\n"
    "  Type /exit to disconnect, /help for commands\r\n"
    "\r\n"
)


class SocketChannel(BaseChannel):
    """TCP socket channel — telnet-like REPL for remote chat.

    Each connection maintains its own conversation history (session isolation).
    Uses the shared :class:`ChatSession` for LLM interaction.
    """

    def __init__(self, host: str = "127.0.0.1", port: int = 9020,
                 shutdown_callback=None) -> None:
        super().__init__(
            "socket",
            enabled=getattr(settings, "daemon_socket_enabled", True),
        )
        self.host = host
        self.port = port
        self._server: asyncio.Server | None = None
        self._session: ChatSession | None = None
        self._shutdown_callback = shutdown_callback

    async def start(self, agent: BaseAgent) -> None:
        await super().start(agent)
        self._session = ChatSession(agent)
        self._server = await asyncio.start_server(
            self._handle_connection, self.host, self.port
        )
        logger.info("SocketChannel listening on %s:%d", self.host, self.port)

    async def stop(self) -> None:
        if self._server:
            self._server.close()
            await self._server.wait_closed()
        logger.info("SocketChannel stopped")

    @property
    def status_detail(self) -> str:
        return f"tcp://{self.host}:{self.port}"

    # ------------------------------------------------------------------
    # per-connection handler
    # ------------------------------------------------------------------

    async def _handle_connection(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        addr = writer.get_extra_info("peername", "unknown")
        session_id = f"socket_{addr[0]}_{addr[1]}"
        logger.info("SocketChannel: new connection from %s (session=%s)", addr, session_id)

        history: list[Any] = []
        writer.write(BANNER.encode("utf-8"))
        await writer.drain()

        while True:
            try:
                writer.write("> ".encode("utf-8"))
                await writer.drain()
                line = await reader.readline()
            except (ConnectionResetError, BrokenPipeError):
                break

            if not line:
                break

            text = line.decode("utf-8", errors="replace").strip()
            if not text:
                continue

            # built-in commands
            if text.startswith("/"):
                if await self._handle_command(text, writer):
                    if text in ("/exit", "/quit", "/q"):
                        break
                    continue

            # set session identity for long-term memory
            self.agent.memory.session_id = session_id
            self.agent.memory.entity_name = session_id
            self.agent.memory.channel = "socket"

            # route through ChatSession with connection-local history
            try:
                response = await self._session.process(
                    user_input=text, history=history, persist=True,
                )
            except Exception as exc:
                response = f"[错误] {exc}"
                logger.error("SocketChannel: agent error for %s: %s", addr, exc)

            # update connection-local history (ChatSession doesn't touch it when history is provided)
            history.append(HumanMessage(content=text))
            history.append(AIMessage(content=response))

            writer.write(f"{response}\r\n\r\n".encode("utf-8"))
            await writer.drain()

            # background fact extraction
            asyncio.create_task(self.agent.extract_facts_async())

        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass
        logger.info("SocketChannel: connection from %s closed", addr)

    # ------------------------------------------------------------------
    # commands
    # ------------------------------------------------------------------

    async def _handle_command(self, text: str, writer: asyncio.StreamWriter) -> bool:
        parts = text.strip().split()
        cmd = parts[0].lower()

        if cmd in ("/exit", "/quit", "/q"):
            writer.write("bye.\r\n".encode("utf-8"))
            await writer.drain()
            return True

        if cmd in ("/shutdown", "/stop"):
            writer.write("shutting down daemon...\r\n".encode("utf-8"))
            await writer.drain()
            if self._shutdown_callback:
                self._shutdown_callback()
            return True

        if cmd == "/help":
            writer.write(
                "  /help       this help\r\n"
                "  /model      show current model\r\n"
                "  /models     list available models\r\n"
                "  /shutdown   stop the daemon\r\n"
                "  /exit       disconnect\r\n"
                .encode("utf-8")
            )
            await writer.drain()
            return True

        if cmd == "/model":
            model = getattr(self.agent.llm, "model_name", None) or "unknown"
            writer.write(f"  current model: {model}\r\n".encode("utf-8"))
            await writer.drain()
            return True

        if cmd == "/models":
            from haven.config import load_models_config
            names = list(load_models_config().keys())
            writer.write(f"  models: {', '.join(names)}\r\n".encode("utf-8"))
            await writer.drain()
            return True

        return False
