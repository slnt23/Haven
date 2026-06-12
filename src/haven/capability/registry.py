"""CapabilityRegistry —— 统一的能力注册中心。

Tool 和 Skill 共用此注册表，不分别维护独立注册器。
支持注册、查询、启用/禁用、按类型过滤。
"""

from __future__ import annotations

import logging
from typing import Any

from haven.capability.models import Capability, Skill, Tool

logger = logging.getLogger("haven.capability.registry")


class CapabilityRegistry:
    """统一的能力注册表。

    所有 Tool 和 Skill 注册到此实例。
    Tool 通过 list_tools() 获取 langchain_tool 列表供 Agent 绑定。
    Skill 通过 list_skills() / get_skill() 查询供 Planner 匹配。

    Usage::

        registry = CapabilityRegistry()
        registry.register(web_search_tool)
        registry.register(data_analysis_skill)

        tools = registry.list_tools()
        skills = registry.list_skills()
    """

    def __init__(self) -> None:
        self._items: dict[str, Capability] = {}

    # ------------------------------------------------------------------
    # 注册
    # ------------------------------------------------------------------

    def register(self, capability: Capability) -> None:
        """注册一个能力。重名时覆盖。"""
        name = capability.name
        if name in self._items:
            logger.debug("Capability '%s' already registered, overwriting", name)
        self._items[name] = capability

    def unregister(self, name: str) -> None:
        """移除一个能力。"""
        self._items.pop(name, None)

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------

    def get(self, name: str) -> Capability:
        """按名称获取能力。不存在时抛出 KeyError。"""
        if name not in self._items:
            keys = list(self._items.keys())
            raise KeyError(f"Capability '{name}' not found. Available: {keys}")
        return self._items[name]

    def get_skill(self, name: str) -> Skill:
        """按名称获取 Skill。"""
        cap = self.get(name)
        if not isinstance(cap, Skill):
            raise KeyError(f"'{name}' is a Tool, not a Skill")
        return cap

    def get_tool(self, name: str) -> Tool:
        """按名称获取 Tool。"""
        cap = self.get(name)
        if not isinstance(cap, Tool):
            raise KeyError(f"'{name}' is a Skill, not a Tool")
        return cap

    def list_all(self) -> dict[str, Capability]:
        """返回所有已注册的能力 {name: Capability}。"""
        return dict(self._items)

    def list_enabled(self) -> dict[str, Capability]:
        """返回所有启用的能力。"""
        return {n: c for n, c in self._items.items() if c.enabled}

    # ------------------------------------------------------------------
    # 类型过滤
    # ------------------------------------------------------------------

    def list_tools(self) -> list[Tool]:
        """返回所有已注册的 Tool（仅启用的）。"""
        return [t for t in self._items.values() if isinstance(t, Tool) and t.enabled]

    def list_skills(self) -> dict[str, Skill]:
        """返回所有已注册的 Skill {name: Skill}（仅启用的）。"""
        return {
            n: s
            for n, s in self._items.items()
            if isinstance(s, Skill) and s.enabled
        }

    def list_langchain_tools(self) -> list[Any]:
        """返回所有 Tool 的底层 LangChain BaseTool 列表。

        这是 Agent 绑定时直接使用的接口。
        """
        return [t.langchain_tool for t in self.list_tools()]

    # ------------------------------------------------------------------
    # Skill 分类查询
    # ------------------------------------------------------------------

    def get_default_skill(self) -> Skill | None:
        """返回 default=True 的人格 Skill。"""
        for s in self._items.values():
            if isinstance(s, Skill) and s.default and s.enabled:
                return s
        return None

    def get_domain_skills(self) -> dict[str, Skill]:
        """返回所有非 default 的领域 Skill。"""
        return {
            n: s
            for n, s in self._items.items()
            if isinstance(s, Skill) and not s.default and s.enabled
        }

    def get_skills_by_tag(self, tag: str) -> list[Skill]:
        """按标签过滤 Skill。"""
        return [
            s
            for s in self._items.values()
            if isinstance(s, Skill) and s.enabled and tag in s.tags
        ]

    def resolve_by_tags(self, tags: list[str]) -> list[str]:
        """按标签交集匹配 Skill，返回名称列表。"""
        matching: list[str] = []
        for name, s in self._items.items():
            if isinstance(s, Skill) and s.enabled and any(t in s.tags for t in tags):
                matching.append(name)
        return matching

    # ------------------------------------------------------------------
    # Provider 过滤
    # ------------------------------------------------------------------

    def list_by_provider(self, provider: str) -> list[Capability]:
        """按 Provider 来源过滤。"""
        return [c for c in self._items.values() if c.metadata.provider == provider]

    # ------------------------------------------------------------------
    # 启用 / 禁用
    # ------------------------------------------------------------------

    def disable(self, name: str) -> None:
        """禁用一个能力。"""
        cap = self.get(name)
        cap.metadata.enabled = False

    def enable(self, name: str) -> None:
        """启用一个能力。"""
        cap = self.get(name)
        cap.metadata.enabled = True

    # ------------------------------------------------------------------
    # 维护
    # ------------------------------------------------------------------

    def clear(self) -> None:
        """清空注册表（测试用）。"""
        self._items.clear()

    @property
    def tool_count(self) -> int:
        return sum(1 for c in self._items.values() if isinstance(c, Tool) and c.enabled)

    @property
    def skill_count(self) -> int:
        return sum(1 for c in self._items.values() if isinstance(c, Skill) and c.enabled)

    def __len__(self) -> int:
        return len(self._items)

    def __contains__(self, name: str) -> bool:
        return name in self._items
