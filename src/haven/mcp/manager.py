from __future__ import annotations

import logging
import os
import re
from contextlib import AsyncExitStack
from typing import Any

from langchain_core.tools import BaseTool

from haven.mcp.config import MCPServerConfig

logger = logging.getLogger("haven.mcp")


class MCPManager:
    """Manages connections to multiple MCP servers.

    Lifecycle::

        manager = MCPManager(configs)
        tools = await manager.start()    # connect all, discover tools
        # ... agent uses tools ...
        await manager.stop()             # graceful shutdown

    Per-server graceful degradation: one offline server never blocks others.
    """

    def __init__(self, server_configs: list[MCPServerConfig] | None = None):
        self._configs: list[MCPServerConfig] = server_configs or []
        self._exit_stack = AsyncExitStack()
        self._tools: dict[str, BaseTool] = {}
        self._active_servers: list[str] = []
        self._failed_servers: list[str] = []
        self._started = False

    # ------------------------------------------------------------------
    # lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> dict[str, BaseTool]:
        """Connect to all enabled MCP servers and discover tools.

        Returns a flat ``{tool_name: BaseTool}`` dict.
        Servers that fail to connect are recorded in ``_failed_servers``.
        """
        if self._started:
            return self._tools

        enabled = [c for c in self._configs if c.enabled]
        if not enabled:
            logger.info("No MCP servers configured or enabled")
            self._started = True
            return self._tools

        for cfg in enabled:
            await self._connect_one(cfg)

        self._started = True
        return self._tools

    async def stop(self) -> None:
        """Gracefully close all MCP sessions."""
        try:
            await self._exit_stack.aclose()
        except Exception as exc:
            logger.debug(f"MCP shutdown: {exc}")
        self._tools.clear()
        self._active_servers.clear()
        self._failed_servers.clear()
        self._started = False

    # ------------------------------------------------------------------
    # tool access
    # ------------------------------------------------------------------

    @property
    def tools(self) -> dict[str, BaseTool]:
        return self._tools

    @property
    def tool_list(self) -> list[BaseTool]:
        """Tools as a flat list — suitable for ``llm.bind_tools()``."""
        return list(self._tools.values())

    @property
    def active_server_count(self) -> int:
        return len(self._active_servers)

    @property
    def failed_server_count(self) -> int:
        return len(self._failed_servers)

    def get_status_summary(self) -> str:
        """Human-readable status for the CLI banner / ``/mcp`` command."""
        if not self._active_servers and not self._failed_servers:
            return "    (none)"

        lines: list[str] = []
        for name in self._active_servers:
            lines.append(f"    ✓ {name}")
        for name in self._failed_servers:
            lines.append(f"    ✗ {name} (offline)")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # internal
    # ------------------------------------------------------------------

    async def _connect_one(self, cfg: MCPServerConfig) -> None:
        """Connect a single server, discover its tools, and register them.

        On failure the server is added to ``_failed_servers`` — other servers
        continue unaffected.
        """
        try:
            if cfg.transport == "stdio":
                await self._connect_stdio(cfg)
            elif cfg.transport == "http":
                await self._connect_http(cfg)
            elif cfg.transport == "websocket":
                await self._connect_websocket(cfg)
            else:
                raise ValueError(f"Unsupported transport: {cfg.transport}")

            self._active_servers.append(cfg.name)
            tool_count = sum(1 for t in self._tools if _tool_belongs_to_server(t, cfg.name))
            logger.info("MCP server '%s': %d tool(s) loaded via %s",
                        cfg.name, tool_count, cfg.transport)

        except Exception as exc:
            self._failed_servers.append(cfg.name)
            logger.warning("MCP server '%s' connection failed: %s", cfg.name, exc)

    async def _connect_stdio(self, cfg: MCPServerConfig) -> None:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
        from langchain_mcp_adapters.tools import load_mcp_tools

        server_params = StdioServerParameters(
            command=cfg.command,
            args=cfg.args,
            env=self._resolve_env_vars(cfg.env) if cfg.env else None,
        )
        transport = await self._exit_stack.enter_async_context(stdio_client(server_params))
        read, write = transport
        session = await self._exit_stack.enter_async_context(ClientSession(read, write))
        await session.initialize()
        tools = await load_mcp_tools(session)
        for tool in tools:
            self._tools[tool.name] = tool

    async def _connect_http(self, cfg: MCPServerConfig) -> None:
        from mcp import ClientSession
        from mcp.client.sse import sse_client
        from langchain_mcp_adapters.tools import load_mcp_tools

        headers = self._resolve_env_vars(cfg.headers) if cfg.headers else {}
        transport = await self._exit_stack.enter_async_context(
            sse_client(cfg.url, headers=headers)
        )
        read, write = transport
        session = await self._exit_stack.enter_async_context(ClientSession(read, write))
        await session.initialize()
        tools = await load_mcp_tools(session)
        for tool in tools:
            self._tools[tool.name] = tool

    async def _connect_websocket(self, cfg: MCPServerConfig) -> None:
        from mcp import ClientSession
        from mcp.client.websocket import websocket_client
        from langchain_mcp_adapters.tools import load_mcp_tools

        transport = await self._exit_stack.enter_async_context(websocket_client(cfg.url))
        read, write = transport
        session = await self._exit_stack.enter_async_context(ClientSession(read, write))
        await session.initialize()
        tools = await load_mcp_tools(session)
        for tool in tools:
            self._tools[tool.name] = tool

    @staticmethod
    def _resolve_env_vars(mapping: dict[str, str]) -> dict[str, str]:
        """Replace ``${VAR}`` patterns with environment variable values."""
        resolved: dict[str, str] = {}
        for key, value in mapping.items():
            resolved[key] = re.sub(
                r"\$\{(\w+)\}",
                lambda m: os.environ.get(m.group(1), ""),
                value,
            )
        return resolved


def _tool_belongs_to_server(tool: BaseTool, server_name: str) -> bool:
    """Heuristic to count tools from a specific server.

    ``langchain-mcp-adapters`` may prefix tool names or attach metadata.
    We try metadata first, then fall back to a name prefix check.
    """
    meta = getattr(tool, "metadata", None) or {}
    if meta.get("server_name") == server_name:
        return True
    if tool.name.startswith(f"{server_name}_") or tool.name.startswith(f"{server_name}."):
        return True
    return True  # can't disambiguate — count it
