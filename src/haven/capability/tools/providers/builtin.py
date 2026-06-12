"""内置工具提供者 —— 自动扫描 ``builtin/`` 目录发现工具。

只需在 ``builtin/`` 下创建 .py 文件，其中的 BaseTool 子类自动被发现。
"""

from __future__ import annotations

import importlib
import inspect
import logging
from pathlib import Path

from langchain_core.tools import BaseTool

from haven.capability.tools.providers.base import ToolProvider

logger = logging.getLogger("haven.capability.tools.builtin")


class BuiltinProvider(ToolProvider):
    """内置工具提供者，自动扫描能力内置工具目录。"""

    def __init__(self, name: str = "builtin") -> None:
        super().__init__(name, provider_type="builtin")
        self.info.description = "Haven 内置工具"

    async def discover(self) -> list[BaseTool]:
        tools: list[BaseTool] = []
        builtin_dir = Path(__file__).resolve().parent.parent / "builtin"

        if not builtin_dir.is_dir():
            logger.debug("builtin/ 目录不存在: %s", builtin_dir)
            return tools

        for py_file in sorted(builtin_dir.glob("*.py")):
            if py_file.name.startswith("_"):
                continue
            try:
                found = self._load_from_file(py_file)
                tools.extend(found)
            except Exception as exc:
                logger.warning("加载内置工具文件失败 %s: %s", py_file.name, exc)

        return tools

    def _load_from_file(self, py_file: Path) -> list[BaseTool]:
        module_name = py_file.stem
        package = "haven.capability.tools.builtin"
        full_name = f"{package}.{module_name}"

        mod = importlib.import_module(full_name)
        tools: list[BaseTool] = []

        for _name, obj in inspect.getmembers(mod, inspect.isclass):
            if not issubclass(obj, BaseTool) or obj is BaseTool:
                continue
            if obj.__module__ != full_name:
                continue
            try:
                instance = obj()
                if isinstance(instance, BaseTool):
                    tools.append(instance)
                    logger.debug("已注册内置工具: %s", instance.name)
            except Exception as exc:
                logger.warning("实例化工具失败 %s: %s", obj.__name__, exc)

        return tools

    async def health_check(self) -> bool:
        return True
