"""ToolManager — 统一工具管理器。

编排所有 ToolProvider 的生命周期（start/stop/refresh）。
全局工具注册表，支持多条件检索和按 skill 过滤。
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from haven.tools.base import HavenTool
from haven.tools.providers.base import ProviderStatus, ToolProvider

logger = logging.getLogger("haven.tools.manager")


class ToolManager:
    """统一工具管理器。

    职责:
      1. Provider 注册/启动/停止/热加载
      2. 全局工具注册表（去重 + 冲突检测）
      3. 多条件工具检索（按名 / 按类别 / 按 provider / 按标签）
      4. 按 skill 需求激活工具子集

    用法::

        tm = ToolManager()
        tm.add_provider(BuiltinProvider())
        tm.add_provider(MCPProvider(cfg))
        await tm.start_all()

        tools = tm.get_tools_for_skills({"coder": ["code_exec"]})
        runtime.bind_tools(tools)
    """

    def __init__(self):
        self._providers: dict[str, ToolProvider] = {}
        self._tools: dict[str, HavenTool] = {}
        self._tool_to_provider: dict[str, str] = {}
        self._started = False

    # ==================================================================
    # Provider 管理
    # ==================================================================

    def add_provider(self, provider: ToolProvider) -> "ToolManager":
        if provider.info.name in self._providers:
            raise ValueError(f"Provider '{provider.info.name}' already registered")
        self._providers[provider.info.name] = provider
        return self

    def remove_provider(self, name: str) -> None:
        if name not in self._providers:
            return
        for t_name in list(self._tool_to_provider):
            if self._tool_to_provider[t_name] == name:
                del self._tools[t_name]
                del self._tool_to_provider[t_name]
        del self._providers[name]

    def get_provider(self, name: str) -> ToolProvider | None:
        return self._providers.get(name)

    def list_providers(self) -> list[ToolProvider]:
        return list(self._providers.values())

    # ==================================================================
    # 生命周期
    # ==================================================================

    async def start_all(self) -> None:
        if self._started:
            return

        results = await asyncio.gather(
            *(self._start_one(p) for p in self._providers.values()),
            return_exceptions=True,
        )
        failed = sum(1 for r in results if isinstance(r, Exception))
        logger.info("ToolManager: %d started, %d failed", len(results) - failed, failed)
        self._started = True

    async def stop_all(self) -> None:
        await asyncio.gather(
            *(p.stop() for p in self._providers.values()),
            return_exceptions=True,
        )
        self._tools.clear()
        self._tool_to_provider.clear()
        self._started = False

    async def refresh_all(self) -> None:
        _results = await asyncio.gather(  # noqa: F841
            *(p.refresh() for p in self._providers.values()),
            return_exceptions=True,
        )
        for provider in self._providers.values():
            self._sync(provider)

    # ==================================================================
    # 工具检索
    # ==================================================================

    def get_tool(self, name: str) -> HavenTool | None:
        return self._tools.get(name)

    def get_tools_for_skills(self, skill_tools: dict[str, list[str]]) -> list[HavenTool]:
        """根据 skill→tools 映射返回工具列表（直接名称匹配）。

        推荐使用 ToolResolver.resolve() 替代此方法——ToolResolver 支持
        标签/类别/能力关键词多级匹配和上下文过滤。
        """
        required: set[str] = set()
        for tool_names in skill_tools.values():
            required.update(tool_names)

        if not required:
            return self.list_all()

        return [t for name, t in self._tools.items() if name in required]

    def get_tools_by_names(self, names: list[str]) -> list[HavenTool]:
        """按精确名称批量获取工具。不存在的名称静默跳过。"""
        return [self._tools[n] for n in names if n in self._tools]

    def get_tools_by_tags(self, tags: list[str]) -> list[HavenTool]:
        """按标签批量获取工具（OR 语义：匹配任一标签）。"""
        result: dict[str, HavenTool] = {}
        for tag in tags:
            for name, tool in self._tools.items():
                if tag in getattr(tool.metadata, "tags", []):
                    result[name] = tool
        return list(result.values())

    def get_tools_by_categories(self, categories: list[str]) -> list[HavenTool]:
        """按类别批量获取工具（OR 语义：匹配任一类别）。"""
        result: dict[str, HavenTool] = {}
        for cat in categories:
            for name, tool in self._tools.items():
                tool_cat = getattr(tool.metadata, "category", None)
                if tool_cat:
                    tc_val = tool_cat.value if hasattr(tool_cat, "value") else str(tool_cat)
                    if tc_val == cat:
                        result[name] = tool
        return list(result.values())

    def get_tools_by_provider(self, provider_name: str) -> list[HavenTool]:
        """获取指定 provider 的所有工具。"""
        return [
            t
            for name, t in self._tools.items()
            if self._tool_to_provider.get(name) == provider_name
        ]

    def filter_tools(
        self,
        *,
        category: str | None = None,
        tag: str | None = None,
        provider: str | None = None,
        only_available: bool = True,
    ) -> list[HavenTool]:
        result: list[HavenTool] = []
        for name, tool in self._tools.items():
            if provider and self._tool_to_provider.get(name) != provider:
                continue
            if category and tool.metadata.category.value != category:
                continue
            if tag and tag not in tool.metadata.tags:
                continue
            if only_available:
                p = self._providers.get(self._tool_to_provider.get(name, ""))
                if p and p.info.status != ProviderStatus.CONNECTED:
                    continue
            result.append(tool)
        return result

    def list_all(self) -> list[HavenTool]:
        return list(self._tools.values())

    def list_names(self) -> list[str]:
        return list(self._tools.keys())

    # ==================================================================
    # 状态
    # ==================================================================

    def get_status(self) -> dict[str, Any]:
        return {
            "providers": {
                name: {
                    "status": p.info.status.value,
                    "tool_count": p.info.tool_count,
                    "error": p.info.last_error,
                }
                for name, p in self._providers.items()
            },
            "total_tools": len(self._tools),
            "available_tools": len(self.filter_tools(only_available=True)),
        }

    def format_status(self) -> str:
        icons = {
            ProviderStatus.CONNECTED: "+",
            ProviderStatus.DEGRADED: "~",
            ProviderStatus.ERROR: "!",
            ProviderStatus.DISCONNECTED: "-",
            ProviderStatus.CONNECTING: ".",
        }
        lines: list[str] = []
        for p in self._providers.values():
            icon = icons.get(p.info.status, "?")
            lines.append(
                f"  {icon} {p.info.name} ({p.info.type})"
                f"  {p.info.tool_count} tools  [{p.info.status.value}]"
            )
            if p.info.last_error:
                lines.append(f"      {p.info.last_error}")
        return "\n".join(lines) if lines else "  (no providers)"

    # ==================================================================
    # 内部
    # ==================================================================

    async def _start_one(self, provider: ToolProvider) -> None:
        await provider.start()
        self._sync(provider)

    def _sync(self, provider: ToolProvider) -> None:
        # 移除旧工具
        for t_name in list(self._tool_to_provider):
            if self._tool_to_provider[t_name] == provider.info.name:
                del self._tools[t_name]
                del self._tool_to_provider[t_name]

        for tool in provider.list_tools():
            if tool.name in self._tools:
                existing = self._tool_to_provider.get(tool.name, "?")
                logger.warning(
                    "Tool collision: '%s' from '%s' overwrites '%s'",
                    tool.name,
                    provider.info.name,
                    existing,
                )
            self._tools[tool.name] = tool
            self._tool_to_provider[tool.name] = provider.info.name
