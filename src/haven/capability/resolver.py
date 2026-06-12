"""DependencyResolver —— Skill 依赖传递闭包解析。

给定一组选中 Skill 名称，递归解析其 dependencies，
返回包含所有传递依赖的完整名称列表。
循环依赖检测 + 缺失依赖警告。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from haven.capability.registry import CapabilityRegistry

logger = logging.getLogger("haven.capability.resolver")


class DependencyResolver:
    """Skill 依赖解析器。

    传递闭包：选中 A (A→B, B→C) → 返回 [A, B, C]。
    循环依赖检测并警告（不阻断）。
    缺失依赖警告并跳过。

    Usage::

        names = DependencyResolver.resolve(["data_analysis"], registry)
    """

    @staticmethod
    def resolve(
        selected: list[str],
        registry: "CapabilityRegistry",
    ) -> list[str]:
        """解析传递依赖，返回完整名称列表（原有顺序 + 依赖附加）。"""
        result: list[str] = list(selected)
        visited: set[str] = set()

        def _walk(name: str, chain: tuple[str, ...]) -> None:
            if name in visited:
                return
            if name in chain:
                logger.warning("循环依赖: %s", " → ".join(chain) + " → " + name)
                return
            visited.add(name)

            try:
                from haven.capability.models import Skill

                cap = registry.get(name)
                if not isinstance(cap, Skill):
                    return
            except KeyError:
                return

            for dep in cap.dependencies:
                if dep not in registry._items:
                    logger.warning("依赖 Skill 未注册: %s (被 %s 依赖)", dep, name)
                    continue
                if dep not in result:
                    result.append(dep)
                _walk(dep, (*chain, name))

        for name in list(selected):
            _walk(name, ())

        if len(result) > len(selected):
            logger.info("依赖解析: 自动激活 %s", set(result) - set(selected))

        return result
