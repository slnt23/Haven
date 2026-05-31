"""BuiltinProvider — 内置工具自动发现。

扫描 tools/ 目录，自动发现所有 HavenTool 子类。
始终可用，无需网络连接。
"""

from __future__ import annotations

import importlib
import inspect
import logging
from pathlib import Path

from haven.tools.base import HavenTool
from haven.tools.providers.base import ToolProvider

logger = logging.getLogger("haven.tools.builtin")

_BUILTIN_MODULES = [
    "haven.tools.code_exec",
    "haven.tools.file_ops",
    "haven.tools.web_search",
    "haven.tools.email_tool",
    "haven.tools.medical",
    "haven.tools.rag_search",
]


class BuiltinProvider(ToolProvider):
    """内置工具提供者。扫描指定模块列表，自动发现 HavenTool 子类。"""

    def __init__(self, name: str = "builtin"):
        super().__init__(name, provider_type="builtin")
        self.info.description = "Haven 内置工具"

    async def discover(self) -> list[HavenTool]:
        tools: list[HavenTool] = []

        for module_path in _BUILTIN_MODULES:
            try:
                module = importlib.import_module(module_path)
                for _, obj in inspect.getmembers(module, inspect.isclass):
                    if (
                        issubclass(obj, HavenTool)
                        and obj is not HavenTool
                        and not inspect.isabstract(obj)
                    ):
                        try:
                            instance = obj()
                            tools.append(instance)
                            logger.debug("Discovered builtin: %s", instance.name)
                        except Exception as exc:
                            logger.debug("Skip %s: %s", obj.__name__, exc)
            except ImportError:
                logger.debug("Module not found: %s", module_path)
            except Exception as exc:
                logger.debug("Failed to scan %s: %s", module_path, exc)

        return tools

    async def health_check(self) -> bool:
        return True
