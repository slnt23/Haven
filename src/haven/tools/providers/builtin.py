"""BuiltinProvider — 内置工具加载。"""

from __future__ import annotations

import importlib
import logging

from langchain_core.tools import StructuredTool

from haven.tools.base import HavenTool, ToolCategory, ToolMetadata, ToolPermission
from haven.tools.providers.base import ToolProvider

logger = logging.getLogger("haven.tools.builtin")

_BUILTIN_MODULES: list[tuple[str, str, str]] = [
    ("web_search", "haven.tools.web_search", "WebSearchTool"),
]

_CATEGORY_MAP: dict[str, ToolCategory] = {
    "web_search": ToolCategory.SEARCH,
}


class BuiltinProvider(ToolProvider):
    """内置工具提供者。"""

    def __init__(self, name: str = "builtin"):
        super().__init__(name, provider_type="builtin")
        self.info.description = "Haven 内置工具"

    async def discover(self) -> list[HavenTool]:
        tools: list[HavenTool] = []

        for tool_name, module_path, class_name in _BUILTIN_MODULES:
            try:
                mod = importlib.import_module(module_path)
                cls = getattr(mod, class_name, None)
                if cls is None:
                    continue
                instance = cls()

                desc = getattr(instance, "description", "") or tool_name
                category = _CATEGORY_MAP.get(tool_name, ToolCategory.CUSTOM)

                lc_tool = StructuredTool.from_function(
                    coroutine=instance.__call__,
                    name=tool_name,
                    description=desc,
                )

                meta = ToolMetadata(
                    provider="builtin",
                    category=category,
                    permissions=[ToolPermission.READ],
                    tags=[tool_name, "builtin"],
                )
                lc_tool.metadata = meta

                tools.append(lc_tool)
                logger.debug("Registered builtin: %s", tool_name)

            except ImportError:
                logger.debug("Module not found: %s", module_path)
            except Exception as exc:
                logger.debug("Failed to load %s: %s", tool_name, exc)

        return tools

    async def health_check(self) -> bool:
        return True
