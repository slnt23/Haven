"""MCPProvider — MCP 服务器工具适配。

一个 Provider 对应一个 MCP 服务器。
自动适配为 HavenTool，工具名加命名空间前缀防止冲突。
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any

from langchain_core.tools import BaseTool as LCBaseTool

from haven.tools.base import HavenTool, ToolCategory, ToolMetadata, ToolPermission
from haven.tools.providers.base import ToolProvider

logger = logging.getLogger("haven.tools.mcp")


class MCPProvider(ToolProvider):
    """MCP 协议工具提供者。

    支持 stdio / HTTP SSE / WebSocket 三种传输。
    工具名自动加命名空间前缀: ``{server_name}__{tool_name}``。
    """

    def __init__(self, server_config: Any):
        super().__init__(name=server_config.name, provider_type="mcp")
        self._config = server_config
        self._session: Any = None
        self._exit_stack: Any = None
        self.info.description = (
            getattr(server_config, "description", "") or f"MCP: {server_config.name}"
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

    # ========== 工具发现 ==========

    async def discover(self) -> list[HavenTool]:
        raw = await self._load_mcp_tools()
        return [self._adapt(t) for t in raw]

    async def _load_mcp_tools(self) -> list[LCBaseTool]:
        try:
            transport = getattr(self._config, "transport", "stdio")
            if transport == "stdio":
                return await self._load_stdio()
            elif transport == "http":
                return await self._load_http()
            elif transport == "websocket":
                return await self._load_websocket()
            else:
                raise ValueError(f"Unsupported transport: {transport}")
        except ImportError:
            logger.debug("MCP SDK not installed")
            return []
        except Exception as exc:
            logger.warning("MCP '%s' failed: %s", self.info.name, exc)
            return []

    async def _load_stdio(self) -> list[LCBaseTool]:
        from langchain_mcp_adapters.tools import load_mcp_tools
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        params = StdioServerParameters(
            command=self._config.command,
            args=getattr(self._config, "args", []),
            env=self._resolve_env(getattr(self._config, "env", {}))
            if getattr(self._config, "env", None)
            else None,
        )
        transport = await self._exit_stack.enter_async_context(stdio_client(params))
        read, write = transport
        session = await self._exit_stack.enter_async_context(ClientSession(read, write))
        await session.initialize()
        self._session = session
        return await load_mcp_tools(session)

    async def _load_http(self) -> list[LCBaseTool]:
        from langchain_mcp_adapters.tools import load_mcp_tools
        from mcp import ClientSession
        from mcp.client.sse import sse_client

        headers = (
            self._resolve_env(getattr(self._config, "headers", {}))
            if getattr(self._config, "headers", None)
            else {}
        )
        transport = await self._exit_stack.enter_async_context(
            sse_client(self._config.url, headers=headers)
        )
        read, write = transport
        session = await self._exit_stack.enter_async_context(ClientSession(read, write))
        await session.initialize()
        self._session = session
        return await load_mcp_tools(session)

    async def _load_websocket(self) -> list[LCBaseTool]:
        from langchain_mcp_adapters.tools import load_mcp_tools
        from mcp import ClientSession
        from mcp.client.websocket import websocket_client

        transport = await self._exit_stack.enter_async_context(websocket_client(self._config.url))
        read, write = transport
        session = await self._exit_stack.enter_async_context(ClientSession(read, write))
        await session.initialize()
        self._session = session
        return await load_mcp_tools(session)

    # ========== 适配 ==========

    def _adapt(self, raw: LCBaseTool) -> HavenTool:
        original = raw.name
        namespaced = f"{self.info.name}__{original}"

        desc = getattr(raw, "description", "") or ""
        category = self._infer_category(original, desc)

        tool = _MCPToolWrapper(
            name=namespaced,
            description=desc or f"MCP tool: {original}",
            metadata=ToolMetadata(
                provider=f"mcp:{self.info.name}",
                category=category,
                permissions=self._infer_permissions(original, desc),
                requires_confirmation=(category == ToolCategory.FILE),
                tags=[
                    f"mcp:{self.info.name}",
                    f"transport:{getattr(self._config, 'transport', 'stdio')}",
                ],
            ),
            _raw=raw,
        )
        return tool

    @staticmethod
    def _infer_category(name: str, desc: str) -> ToolCategory:
        combined = f"{name} {desc}".lower()
        if any(k in combined for k in ("file", "read_file", "write_file", "directory", "path")):
            return ToolCategory.FILE
        if any(k in combined for k in ("search", "query", "fetch", "lookup", "find")):
            return ToolCategory.SEARCH
        if any(k in combined for k in ("email", "mail", "send", "notify")):
            return ToolCategory.COMMUNICATION
        if any(k in combined for k in ("exec", "code", "run", "shell")):
            return ToolCategory.CODE
        return ToolCategory.CUSTOM

    @staticmethod
    def _infer_permissions(name: str, desc: str) -> list[ToolPermission]:
        combined = f"{name} {desc}".lower()
        perms = [ToolPermission.READ]
        if any(k in combined for k in ("write", "create", "delete", "remove", "update")):
            perms.append(ToolPermission.WRITE)
        if any(k in combined for k in ("exec", "run", "shell", "code")):
            perms.append(ToolPermission.EXECUTE)
        if any(k in combined for k in ("send", "email", "notify")):
            perms.append(ToolPermission.SEND)
        return perms

    async def health_check(self) -> bool:
        return self._session is not None

    @staticmethod
    def _resolve_env(mapping: dict[str, str]) -> dict[str, str]:
        return {
            k: re.sub(r"\$\{(\w+)\}", lambda m: os.environ.get(m.group(1), ""), v)
            for k, v in mapping.items()
        }


class _MCPToolWrapper(HavenTool):
    """MCP 工具轻量包装器。"""

    def __init__(self, _raw: LCBaseTool, **kwargs: Any):
        super().__init__(**kwargs)
        self._raw = _raw

    async def _arun(self, *args: Any, **kwargs: Any) -> Any:
        if hasattr(self._raw, "ainvoke"):
            return await self._raw.ainvoke(kwargs if kwargs else (args[0] if args else {}))
        return self._raw._run(*args, **kwargs)

    def _run(self, *args: Any, **kwargs: Any) -> Any:
        return self._raw._run(*args, **kwargs)
