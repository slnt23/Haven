"""工具注册中心 —— 纯 CRUD，不做任何推理或选择。

所有 Provider 发现的工具统一注册到此，Runtime 层通过 ``registry.list()``
获取完整工具列表后直接交给 Agent。LLM 自行决定调用哪个工具。
"""

from __future__ import annotations

import logging

from langchain_core.tools import BaseTool

logger = logging.getLogger("haven.tools.registry")


class ToolRegistry:
    """扁平工具注册表，横跨所有 Provider。

    用法::

        reg = ToolRegistry()
        reg.register(tool, provider="builtin")  # 注册单个工具
        tools = reg.list()                       # 获取全部工具列表
    """

    def __init__(self) -> None:
        # 工具名 → 工具实例
        self._tools: dict[str, BaseTool] = {}
        # 工具名 → 所属 provider 名（用于来源追踪和批量卸载）
        self._tool_provider: dict[str, str] = {}

    # ------------------------------------------------------------------
    # 单个工具操作
    # ------------------------------------------------------------------

    def register(self, tool: BaseTool, *, provider: str = "") -> None:
        """注册一个工具。同名工具后注册的覆盖先注册的，并记录警告。"""
        if tool.name in self._tools:
            prev = self._tool_provider.get(tool.name, "?")
            logger.debug(
                "工具 '%s'（来自 '%s'）覆盖了 '%s' 的注册",
                tool.name, provider, prev,
            )
        self._tools[tool.name] = tool
        self._tool_provider[tool.name] = provider

    def unregister(self, name: str) -> None:
        """按名称移除单个工具。"""
        self._tools.pop(name, None)
        self._tool_provider.pop(name, None)

    def get(self, name: str) -> BaseTool | None:
        """按名称精确查找工具，不存在返回 None。"""
        return self._tools.get(name)

    def list(self) -> list[BaseTool]:
        """返回全部已注册工具的扁平列表，可直接传入 create_react_agent。"""
        return list(self._tools.values())

    def list_names(self) -> list[str]:
        """返回全部已注册工具的名称列表（轻量查询）。"""
        return list(self._tools.keys())

    def list_by_provider(self, provider: str) -> list[BaseTool]:
        """按提供者名称过滤工具列表。"""
        return [
            t for name, t in self._tools.items()
            if self._tool_provider.get(name) == provider
        ]

    # ------------------------------------------------------------------
    # 批量操作
    # ------------------------------------------------------------------

    def unregister_provider(self, provider: str) -> int:
        """移除指定提供者的所有工具，返回移除数量。
        用于 Provider 断连或卸载时批量清理。
        """
        names = [
            n for n, p in self._tool_provider.items() if p == provider
        ]
        for n in names:
            del self._tools[n]
            del self._tool_provider[n]
        return len(names)

    def clear(self) -> None:
        """清空全部注册记录。"""
        self._tools.clear()
        self._tool_provider.clear()

    @property
    def tool_count(self) -> int:
        """当前已注册工具总数。"""
        return len(self._tools)
