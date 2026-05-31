"""CustomProvider — 用户自定义工具提供者。

支持装饰器注册和直接注册 HavenTool 实例。
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable

from haven.tools.base import HavenTool, ToolMetadata, ToolCategory, ToolPermission
from haven.tools.providers.base import ToolProvider

logger = logging.getLogger("haven.tools.custom")


class CustomProvider(ToolProvider):
    """用户自定义工具提供者。

    用法::

        provider = CustomProvider("my_tools")

        @provider.register(name="hello", description="Say hello", category=ToolCategory.CUSTOM)
        async def hello(name: str) -> str:
            return f"Hello, {name}!"
    """

    def __init__(self, name: str = "custom"):
        super().__init__(name, provider_type="custom")
        self.info.description = "用户自定义工具"
        self._pending: list[HavenTool] = []

    async def discover(self) -> list[HavenTool]:
        return list(self._pending)

    async def health_check(self) -> bool:
        return True

    # ========== 注册 API ==========

    def register(
        self,
        *,
        name: str,
        description: str = "",
        category: ToolCategory = ToolCategory.CUSTOM,
        permissions: list[ToolPermission] | None = None,
        requires_confirmation: bool = False,
        tags: list[str] | None = None,
    ) -> Callable:
        """装饰器：将 async 函数注册为 HavenTool。"""

        def decorator(func: Callable) -> HavenTool:
            tool = _FunctionToolWrapper(
                name=name,
                description=description or func.__doc__ or f"Custom: {name}",
                metadata=ToolMetadata(
                    provider=f"custom:{self.info.name}",
                    category=category,
                    permissions=permissions or [ToolPermission.READ],
                    requires_confirmation=requires_confirmation,
                    tags=tags or [],
                ),
                _func=func,
            )
            self._pending.append(tool)
            logger.debug("Custom tool registered: %s", name)
            return tool

        return decorator

    def register_tool(self, tool: HavenTool) -> None:
        """直接注册 HavenTool 实例。"""
        tool.metadata.provider = f"custom:{self.info.name}"
        self._pending.append(tool)

    def unregister(self, name: str) -> bool:
        for i, t in enumerate(self._pending):
            if t.name == name:
                self._pending.pop(i)
                return True
        return False


class _FunctionToolWrapper(HavenTool):
    """函数工具包装器。"""

    def __init__(self, _func: Callable, **kwargs: Any):
        super().__init__(**kwargs)
        self._func = _func

    async def _arun(self, *args: Any, **kwargs: Any) -> Any:
        result = self._func(**kwargs)
        if asyncio.iscoroutine(result):
            return await result
        return result

    def _run(self, *args: Any, **kwargs: Any) -> Any:
        return asyncio.run(self._arun(*args, **kwargs))
