"""MCP 协议提供者 —— 连接 MCP 服务器，将其工具适配为 BaseTool。

每个 MCP 服务器对应一个 MCPProvider 实例。工具名自动加命名空间前缀
``{server_name}__{tool_name}``，避免不同服务器的同名工具冲突。

支持的传输方式：
  - stdio     — 本地命令行工具（如 npx + MCP server）
  - http      — HTTP SSE（Server-Sent Events）
  - websocket — WebSocket 双向通信

环境变量解析：
  配置中 ``env`` 字段的值支持 ``${VAR_NAME}`` 语法，自动从 os.environ 读取。
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any

from langchain_core.tools import BaseTool

from haven.tools.metadata import ToolMetadata
from haven.tools.providers.base import ToolProvider

logger = logging.getLogger("haven.tools.mcp")


class MCPProvider(ToolProvider):
    """MCP 协议工具提供者。

    启动流程：
      1. 创建 AsyncExitStack（管理连接生命周期）
      2. 根据 transport 类型建立连接
      3. ClientSession.initialize() 握手
      4. load_mcp_tools() 获取原始工具列表
      5. _adapt() 为每个工具加命名空间前缀 + metadata
    """

    def __init__(self, server_config: Any) -> None:
        super().__init__(name=server_config.name, provider_type="mcp")
        self._config = server_config  # MCPServerConfig 实例
        self._session: Any = None  # MCP ClientSession
        self._exit_stack: Any = None  # AsyncExitStack，统一清理资源
        self.info.description = (
            getattr(server_config, "description", "")
            or f"MCP: {server_config.name}"
        )

    # ------------------------------------------------------------------
    # 生命周期钩子
    # ------------------------------------------------------------------

    async def _on_start(self) -> None:
        """创建 AsyncExitStack，后续所有异步上下文都注册到其中。"""
        from contextlib import AsyncExitStack
        self._exit_stack = AsyncExitStack()

    async def _on_stop(self) -> None:
        """关闭 AsyncExitStack → 自动清理所有嵌套的异步上下文。"""
        if self._exit_stack:
            try:
                await self._exit_stack.aclose()
            except Exception:
                pass
        self._session = None

    # ------------------------------------------------------------------
    # 工具发现
    # ------------------------------------------------------------------

    async def discover(self) -> list[BaseTool]:
        """加载 MCP 工具并适配为 BaseTool。"""
        raw = await self._load_mcp_tools()  # 从 MCP 服务器获取原始工具
        return [self._adapt(t) for t in raw]  # 逐个适配（加命名空间）

    async def _load_mcp_tools(self) -> list[BaseTool]:
        """根据 transport 类型分发到对应的加载方法。"""
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
        """通过 stdio 子进程连接 MCP 服务器。"""
        from mcp import StdioServerParameters
        from mcp.client.stdio import stdio_client

        params = StdioServerParameters(
            command=self._config.command,  # 可执行文件路径
            args=getattr(self._config, "args", []),  # 命令行参数
            env=self._resolve_env(getattr(self._config, "env", {}))
            if getattr(self._config, "env", None)
            else None,  # 环境变量（支持 ${VAR} 替换）
        )
        return await self._load_via_transport(stdio_client(params))

    async def _load_http(self) -> list[BaseTool]:
        """通过 HTTP SSE 连接远程 MCP 服务器。"""
        from mcp.client.sse import sse_client

        # 解析 headers 中的环境变量
        headers = (
            self._resolve_env(getattr(self._config, "headers", {}))
            if getattr(self._config, "headers", None)
            else {}
        )
        return await self._load_via_transport(sse_client(self._config.url, headers=headers))

    async def _load_websocket(self) -> list[BaseTool]:
        """通过 WebSocket 连接 MCP 服务器。"""
        from mcp.client.websocket import websocket_client

        return await self._load_via_transport(websocket_client(self._config.url))

    async def _load_via_transport(self, transport_ctx: Any) -> list[BaseTool]:
        """通用的传输层加载流程：
        1. 进入传输上下文 → 获取 read/write 流
        2. 创建 ClientSession → initialize 握手
        3. 调用 langchain_mcp_adapters 加载工具
        """
        from langchain_mcp_adapters.tools import load_mcp_tools
        from mcp import ClientSession

        # 将传输注册到 exit_stack，stop 时自动清理
        transport = await self._exit_stack.enter_async_context(transport_ctx)
        read, write = transport
        session = await self._exit_stack.enter_async_context(ClientSession(read, write))
        await session.initialize()  # MCP 握手
        self._session = session
        return await load_mcp_tools(session)  # 返回 LangChain BaseTool 列表

    # ------------------------------------------------------------------
    # 工具适配
    # ------------------------------------------------------------------

    def _adapt(self, raw: BaseTool) -> BaseTool:
        """为 MCP 工具加命名空间前缀并附加 metadata。

        不做类别推断、权限推断 —— 工具选择完全由 LLM 决定。
        """
        original = raw.name
        namespaced = f"{self.info.name}__{original}"  # 双下划线分隔

        wrapper = _MCPToolWrapper(
            name=namespaced,
            description=getattr(raw, "description", "") or f"MCP tool: {original}",
            metadata=ToolMetadata(
                provider=f"mcp:{self.info.name}",
                requires_confirmation=False,
            ),
            _raw=raw,  # 保留原始工具引用
        )
        return wrapper

    async def health_check(self) -> bool:
        """MCP 服务器可用性检查：session 存在即视为健康。"""
        return self._session is not None

    @staticmethod
    def _resolve_env(mapping: dict[str, str]) -> dict[str, str]:
        """解析 ${VAR_NAME} 环境变量占位符。

        例如 ``{"API_KEY": "${MY_API_KEY}"}`` → 从 os.environ 读取 MY_API_KEY。
        """
        return {
            k: re.sub(
                r"\$\{(\w+)\}",
                lambda m: os.environ.get(m.group(1), ""),  # 未找到的变量替换为空字符串
                v,
            )
            for k, v in mapping.items()
        }


class _MCPToolWrapper(BaseTool):
    """MCP 工具轻量包装器。

    将原始 LangChain BaseTool 委托调用，同时携带 Haven 的 ToolMetadata。
    工具名已由 MCPProvider._adapt() 加上命名空间前缀。
    """

    def __init__(self, _raw: BaseTool, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._raw = _raw  # 原始 MCP 工具实例

    async def _arun(self, *args: Any, **kwargs: Any) -> Any:
        """异步执行：优先使用 ainvoke，回退到 _run。"""
        if hasattr(self._raw, "ainvoke"):
            return await self._raw.ainvoke(
                kwargs if kwargs else (args[0] if args else {})
            )
        return self._raw._run(*args, **kwargs)

    def _run(self, *args: Any, **kwargs: Any) -> Any:
        """同步执行：直接委托给原始工具。"""
        return self._raw._run(*args, **kwargs)
