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
    """管理多个 MCP 服务器的连接。

    生命周期::

        manager = MCPManager(configs)
        tools = await manager.start()    # 连接全部，发现工具
        # ... agent 使用工具 ...
        await manager.stop()             # 优雅关闭

    单服务器故障不影响其他服务器运行。
    """

    def __init__(self, server_configs: list[MCPServerConfig] | None = None):
        self._configs: list[MCPServerConfig] = server_configs or []
        self._exit_stack = AsyncExitStack()
        self._tools: dict[str, BaseTool] = {}
        self._active_servers: list[str] = []
        self._failed_servers: list[str] = []
        self._started = False

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------

    async def start(self) -> dict[str, BaseTool]:
        """连接所有启用的 MCP 服务器并发现工具。

        返回 ``{tool_name: BaseTool}`` 字典。
        连接失败的服务器记录在 ``_failed_servers`` 中。
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
        """优雅关闭所有 MCP 会话。"""
        try:
            await self._exit_stack.aclose()
        except Exception as exc:
            logger.debug(f"MCP shutdown: {exc}")
        self._tools.clear()
        self._active_servers.clear()
        self._failed_servers.clear()
        self._started = False

    # ------------------------------------------------------------------
    # 工具访问
    # ------------------------------------------------------------------

    @property
    def tools(self) -> dict[str, BaseTool]:
        return self._tools

    @property
    def tool_list(self) -> list[BaseTool]:
        """工具平铺列表——适合 ``llm.bind_tools()``。"""
        return list(self._tools.values())

    @property
    def active_server_count(self) -> int:
        return len(self._active_servers)

    @property
    def failed_server_count(self) -> int:
        return len(self._failed_servers)

    def get_status_summary(self) -> str:
        """CLI banner / ``/mcp`` 命令的可读状态信息。"""
        if not self._active_servers and not self._failed_servers:
            return "    (none)"

        lines: list[str] = []
        for name in self._active_servers:
            lines.append(f"    ✓ {name}")
        for name in self._failed_servers:
            lines.append(f"    ✗ {name} (offline)")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # 内部实现
    # ------------------------------------------------------------------

    async def _connect_one(self, cfg: MCPServerConfig) -> None:
        """连接单个服务器，发现并注册其工具。

        失败时服务器记入 ``_failed_servers``——其他服务器不受影响。
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
        """将 ``${VAR}`` 模式替换为环境变量值。"""
        resolved: dict[str, str] = {}
        for key, value in mapping.items():
            resolved[key] = re.sub(
                r"\$\{(\w+)\}",
                lambda m: os.environ.get(m.group(1), ""),
                value,
            )
        return resolved


def _tool_belongs_to_server(tool: BaseTool, server_name: str) -> bool:
    """判断工具是否属于指定服务器的启发式方法。

    ``langchain-mcp-adapters`` 可能给工具名加前缀或附加元数据。
    先尝试 metadata，再回退到名称前缀检查。
    """
    meta = getattr(tool, "metadata", None) or {}
    if meta.get("server_name") == server_name:
        return True
    if tool.name.startswith(f"{server_name}_") or tool.name.startswith(f"{server_name}."):
        return True
    return True  # 无法区分——计入该服务器
