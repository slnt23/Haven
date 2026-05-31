"""BuiltinProvider — 内置工具自动发现。

通过 importlib 加载 6 个内置工具模块，实例化后包装为 LangChain StructuredTool。
"""

from __future__ import annotations

import importlib
import logging
from typing import Any

from langchain_core.tools import StructuredTool

from haven.tools.base import HavenTool, ToolMetadata, ToolCategory, ToolPermission
from haven.tools.providers.base import ToolProvider

logger = logging.getLogger("haven.tools.builtin")

_BUILTIN_MODULES: list[tuple[str, str, str]] = [
    ("code_exec",  "haven.tools.code_exec",  "CodeExecTool"),
    ("file_ops",   "haven.tools.file_ops",   "FileOpsTool"),
    ("web_search", "haven.tools.web_search", "WebSearchTool"),
    ("rag_search", "haven.tools.rag_search", "RAGSearchTool"),
    ("medical_kb", "haven.tools.medical",    "MedicalKnowledgeTool"),
    ("email",      "haven.tools.email_tool", "EmailSenderTool"),
]

_CATEGORY_MAP: dict[str, ToolCategory] = {
    "code_exec":  ToolCategory.CODE,
    "file_ops":   ToolCategory.FILE,
    "web_search": ToolCategory.SEARCH,
    "rag_search": ToolCategory.KNOWLEDGE,
    "medical_kb": ToolCategory.KNOWLEDGE,
    "email":      ToolCategory.COMMUNICATION,
}


class BuiltinProvider(ToolProvider):
    """内置工具提供者。始终可用，零配置。"""

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
                setattr(lc_tool, "metadata", meta)

                tools.append(lc_tool)
                logger.debug("Registered builtin: %s", tool_name)

            except ImportError:
                logger.debug("Module not found: %s", module_path)
            except Exception as exc:
                logger.debug("Failed to load %s: %s", tool_name, exc)

        return tools

    async def health_check(self) -> bool:
        return True
