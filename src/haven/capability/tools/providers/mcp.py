"""MCP 协议提供者 —— 连接 MCP 服务器，将其工具适配为 BaseTool。

支持 stdio / HTTP SSE / WebSocket 传输。
工具名自动加命名空间前缀 ``{server_name}__{tool_name}``。
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any

from langchain_core.tools import BaseTool

from haven.capability.tools.providers.base import ToolProvider

logger = logging.getLogger("haven.capability.tools.mcp")


class MCPProvider(ToolProvider):
    """MCP 协议工具提供者。"""

    def __init__(self, server_config: Any) -> None:
        super().__init__(name=server_config.name, provider_type="mcp")
        self._config = server_config
        self._session: Any = None
        self._exit_stack: Any = None
        self.info.description = (
            getattr(server_config, "description", "")
            or f"MCP: {server_config.name}"
        )

    async def _on_start(self) -> None:
        from contextlib import AsyncExitStack
        self._exit_stack = AsyncExitStack()

    async def _on_stop(self) -> None:
        if self._exit_stack:
            try:
                await self._exit_stack.aclose()
            except Exception:
                pass
        self._session = None

    async def discover(self) -> list[BaseTool]:
        raw = await self._load_mcp_tools()
        return [self._adapt(t) for t in raw]

    async def _load_mcp_tools(self) -> list[BaseTool]:
        try:
            transport = getattr(self._config, "transport", "stdio")
            if transport == "stdio":
                return await self._load_stdio()
            elif transport == "http":
                return await self._load_http()
            elif transport == "websocket":
                return await self._load_websocket()
            else:
                raise ValueError(f"不支持的传输方式: {transport}")
        except ImportError:
            logger.debug("MCP SDK 未安装")
            return []
        except Exception as exc:
            logger.warning("MCP '%s' 加载失败: %s", self.info.name, exc)
            return []

    async def _load_stdio(self) -> list[BaseTool]:
        from mcp import StdioServerParameters
        from mcp.client.stdio import stdio_client

        params = StdioServerParameters(
            command=self._config.command,
            args=getattr(self._config, "args", []),
            env=self._resolve_env(getattr(self._config, "env", {}))
            if getattr(self._config, "env", None) else None,
        )
        return await self._load_via_transport(stdio_client(params))

    async def _load_http(self) -> list[BaseTool]:
        from mcp.client.sse import sse_client

        headers = (
            self._resolve_env(getattr(self._config, "headers", {}))
            if getattr(self._config, "headers", None) else {}
        )
        return await self._load_via_transport(sse_client(self._config.url, headers=headers))

    async def _load_websocket(self) -> list[BaseTool]:
        from mcp.client.websocket import websocket_client
        return await self._load_via_transport(websocket_client(self._config.url))

    async def _load_via_transport(self, transport_ctx: Any) -> list[BaseTool]:
        from langchain_mcp_adapters.tools import load_mcp_tools
        from mcp import ClientSession

        transport = await self._exit_stack.enter_async_context(transport_ctx)
        read, write = transport
        session = await self._exit_stack.enter_async_context(ClientSession(read, write))
        await session.initialize()
        self._session = session
        return await load_mcp_tools(session)

    def _adapt(self, raw: BaseTool) -> BaseTool:
        original = raw.name
        namespaced = f"{self.info.name}__{original}"
        return _MCPToolWrapper(
            name=namespaced,
            description=getattr(raw, "description", "") or f"MCP tool: {original}",
            _raw=raw,
        )

    async def health_check(self) -> bool:
        return self._session is not None

    @staticmethod
    def _resolve_env(mapping: dict[str, str]) -> dict[str, str]:
        return {
            k: re.sub(
                r"\$\{(\w+)\}",
                lambda m: os.environ.get(m.group(1), ""),
                v,
            )
            for k, v in mapping.items()
        }


class _MCPToolWrapper(BaseTool):
    """MCP 工具轻量包装器，委托给原始 BaseTool。"""

    _raw: BaseTool

    def __init__(self, _raw: BaseTool, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._raw = _raw

    async def _arun(self, *args: Any, **kwargs: Any) -> Any:
        if hasattr(self._raw, "ainvoke"):
            return await self._raw.ainvoke(
                kwargs if kwargs else (args[0] if args else {})
            )
        return self._raw._run(*args, **kwargs)

    def _run(self, *args: Any, **kwargs: Any) -> Any:
        return self._raw._run(*args, **kwargs)
