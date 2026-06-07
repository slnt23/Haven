"""内置工具提供者 —— 自动扫描 ``builtin/`` 目录发现工具。

不需要手动注册，只需在 ``builtin/`` 目录下创建 .py 文件，
其中定义 BaseTool 子类即可被自动发现。

发现规则：
  - 扫描 ``builtin/*.py``（跳过以 ``_`` 开头的文件）
  - 找到所有 BaseTool 子类（排除导入的基类，仅实例化本模块定义的类）
  - 自动附加 ToolMetadata（provider="builtin"）
"""

from __future__ import annotations

import importlib
import inspect
import logging
from pathlib import Path

from langchain_core.tools import BaseTool

from haven.tools.metadata import ToolMetadata
from haven.tools.providers.base import ToolProvider

logger = logging.getLogger("haven.tools.builtin")


class BuiltinProvider(ToolProvider):
    """内置工具提供者，自动扫描 ``builtin/`` 包。

    用法：把工具 .py 文件放入 ``builtin/`` 目录即可，零配置。
    """

    def __init__(self, name: str = "builtin") -> None:
        super().__init__(name, provider_type="builtin")
        self.info.description = "Haven 内置工具"

    async def discover(self) -> list[BaseTool]:
        """扫描 builtin/ 目录，加载所有 BaseTool 子类。"""
        tools: list[BaseTool] = []
        # builtin/ 位于 tools/ 的同级子目录
        builtin_dir = Path(__file__).resolve().parent.parent / "builtin"

        if not builtin_dir.is_dir():
            logger.debug("builtin/ 目录不存在: %s", builtin_dir)
            return tools

        # 遍历 .py 文件，按文件名排序保证加载顺序稳定
        for py_file in sorted(builtin_dir.glob("*.py")):
            if py_file.name.startswith("_"):  # 跳过 __init__.py 等
                continue
            try:
                found = self._load_from_file(py_file)
                tools.extend(found)
            except Exception as exc:
                logger.warning("加载内置工具文件失败 %s: %s", py_file.name, exc)

        return tools

    def _load_from_file(self, py_file: Path) -> list[BaseTool]:
        """从单个 .py 文件中加载所有 BaseTool 子类。

        仅实例化本模块定义的类（排除 import 进来的基类）。
        """
        module_name = py_file.stem  # 文件名去掉 .py
        package = "haven.tools.builtin"
        full_name = f"{package}.{module_name}"

        # 动态导入模块
        mod = importlib.import_module(full_name)

        tools: list[BaseTool] = []
        for _name, obj in inspect.getmembers(mod, inspect.isclass):
            # 过滤：必须是 BaseTool 子类，但不能是 BaseTool 本身
            if not issubclass(obj, BaseTool) or obj is BaseTool:
                continue
            # 仅实例化本模块定义的类，排除从其他模块 import 的
            if obj.__module__ != full_name:
                continue
            try:
                instance = obj()  # 无参构造
                if not isinstance(instance, BaseTool):
                    continue
                # 自动补全 metadata
                if not hasattr(instance, "metadata") or instance.metadata is None:
                    instance.metadata = ToolMetadata(provider="builtin")
                elif instance.metadata.provider == "":
                    instance.metadata.provider = "builtin"
                tools.append(instance)
                logger.debug("已注册内置工具: %s", instance.name)
            except Exception as exc:
                logger.warning("实例化工具失败 %s: %s", obj.__name__, exc)

        return tools

    async def health_check(self) -> bool:
        """内置工具无需外部连接，始终可用。"""
        return True
