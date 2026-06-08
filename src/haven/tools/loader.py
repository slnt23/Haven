"""工具加载器 —— 统一的工具发现、加载、注册入口。

启动时扫描内置工具目录 + MCP 配置，启动所有 Provider，将发现的工具
注册到 ToolRegistry，最终返回 ``list[BaseTool]`` 供 Agent 使用。

用法::

    loader = ToolLoader()
    tools = await loader.load_all(load_mcp=True)
    agent = create_agent(model=model, tools=tools)
"""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.tools import BaseTool

from haven.config import settings
from haven.tools.providers.base import ToolProvider
from haven.tools.providers.builtin import BuiltinProvider
from haven.tools.registry import ToolRegistry

logger = logging.getLogger("haven.tools.loader")


class ToolLoader:
    """工具加载器，编排所有 Provider 的生命周期。

    属性：
      - registry: ToolRegistry 实例，加载完成后包含全部工具
    """

    def __init__(self) -> None:
        self.registry = ToolRegistry()  # 全局工具注册中心
        self._providers: dict[str, ToolProvider] = {}  # name → provider
        self._started = False  # 是否已完成首次加载

    # ------------------------------------------------------------------
    # 公开 API
    # ------------------------------------------------------------------

    async def load_all(self, *, load_mcp: bool = True) -> list[BaseTool]:
        """加载全部工具，返回扁平列表供 Agent 绑定。

        加载流程：
          1. 启动 BuiltinProvider → 自动扫描 ``builtin/`` 目录
          2. 如果 load_mcp=True，解析 mcp.json → 为每个启用的服务器创建 MCPProvider
          3. 并行启动所有 Provider → 发现的工具注册到 registry
          4. 返回 registry.list()

        重复调用不会重新加载（幂等）。
        """
        if self._started:  # 已加载，直接返回
            return self.registry.list()

        # 步骤 1：内置工具
        builtin = BuiltinProvider()
        self._add_provider(builtin)

        # 步骤 2：MCP 工具
        if load_mcp and settings.mcp_enabled:
            for cfg in self._load_mcp_configs():
                from haven.tools.providers.mcp import MCPProvider
                self._add_provider(MCPProvider(cfg))

        # 步骤 3：并行启动所有 Provider
        await self._start_all()
        self._started = True

        tools = self.registry.list()
        logger.info(
            "ToolLoader: 从 %d 个提供者加载了 %d 个工具",
            len(self._providers), len(tools),
        )
        return tools

    async def stop_all(self) -> None:
        """停止所有 Provider 并清空注册表。"""
        import asyncio

        # 并行停止所有 Provider（单个失败不影响其他）
        await asyncio.gather(
            *(p.stop() for p in self._providers.values()),
            return_exceptions=True,
        )
        self.registry.clear()
        self._providers.clear()
        self._started = False

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    def _add_provider(self, provider: ToolProvider) -> None:
        """将 Provider 加入管理列表。"""
        self._providers[provider.info.name] = provider

    async def _start_all(self) -> None:
        """并行启动所有 Provider，单个失败不影响其他。"""
        import asyncio

        async def _start_one(p: ToolProvider) -> None:
            """启动单个 Provider 并将其工具注册到 registry。"""
            await p.start()  # Provider 内部完成 discover()
            for tool in p.list_tools():
                self.registry.register(tool, provider=p.info.name)

        # 并行启动，捕获异常避免单点故障
        results = await asyncio.gather(
            *(_start_one(p) for p in self._providers.values()),
            return_exceptions=True,
        )
        failed = sum(1 for r in results if isinstance(r, Exception))
        if failed:
            logger.warning("ToolLoader: %d 个提供者启动失败", failed)

    @staticmethod
    def _load_mcp_configs() -> list[Any]:
        """从 mcp.json 加载 MCP 服务器配置，过滤 enabled=false 的条目。"""
        from haven.config import get_mcp_config
        from haven.config.mcp import MCPServerConfig

        raw = get_mcp_config()
        configs: list[Any] = []
        for entry in raw:
            try:
                cfg = MCPServerConfig(**entry)
                if cfg.enabled:  # 仅加载启用的服务器
                    configs.append(cfg)
            except Exception:
                continue
        return configs
