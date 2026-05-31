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
    """TCP socket 通道——类 telnet 的远程聊天 REPL。

    每个连接维护独立的对话历史（会话隔离）。
    通过共享 :class:`ChatSession` 与 LLM 交互。
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
    # 按连接处理
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

            # 内置命令
            if text.startswith("/"):
                if await self._handle_command(text, writer):
                    if text in ("/exit", "/quit", "/q"):
                        break
                    continue

            # 设置会话身份（用于长期记忆）
            self.agent.memory.session_id = session_id
            self.agent.memory.entity_name = session_id
            self.agent.memory.channel = "socket"

            # 通过 ChatSession 处理（使用连接本地历史）
            try:
                response = await self._session.process(
                    user_input=text, history=history, persist=True,
                )
            except Exception as exc:
                response = f"[错误] {exc}"
                logger.error("SocketChannel: agent error for %s: %s", addr, exc)

            # 更新连接本地历史（提供 history 时 ChatSession 不操作短期记忆）
            history.append(HumanMessage(content=text))
            history.append(AIMessage(content=response))

            writer.write(f"{response}\r\n\r\n".encode("utf-8"))
            await writer.drain()

            # 后台事实提取
            asyncio.create_task(self.agent.extract_facts_async())

        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass
        logger.info("SocketChannel: connection from %s closed", addr)

    # ------------------------------------------------------------------
    # 命令处理
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
