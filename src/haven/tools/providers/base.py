"""ToolProvider — 工具提供者抽象基类。

每种工具来源实现一个 Provider。ToolManager 统一编排生命周期。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum

from haven.tools.base import HavenTool


class ProviderStatus(str, Enum):
    UNINITIALIZED = "uninitialized"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    DEGRADED = "degraded"
    DISCONNECTED = "disconnected"
    ERROR = "error"


@dataclass
class ProviderInfo:
    name: str
    type: str = "custom"
    description: str = ""
    version: str = "1.0"
    tool_count: int = 0
    status: ProviderStatus = ProviderStatus.UNINITIALIZED
    last_error: str = ""


class ToolProvider(ABC):
    """工具提供者抽象基类。

    子类实现:
      - discover(): 发现工具 → list[HavenTool]
      - health_check(): 可用性检查

    可选覆盖:
      - _on_start(): 初始化连接
      - _on_stop(): 释放资源
    """

    def __init__(self, name: str, provider_type: str = "custom"):
        self.info = ProviderInfo(name=name, type=provider_type)
        self._tools: dict[str, HavenTool] = {}

    # ==================================================================
    # 生命周期
    # ==================================================================

    async def start(self) -> None:
        self.info.status = ProviderStatus.CONNECTING
        try:
            await self._on_start()
            await self.refresh()
            self.info.status = ProviderStatus.CONNECTED
        except Exception as exc:
            self.info.status = ProviderStatus.ERROR
            self.info.last_error = str(exc)
            raise

    async def stop(self) -> None:
        try:
            await self._on_stop()
        finally:
            self.info.status = ProviderStatus.DISCONNECTED
            self._tools.clear()

    async def refresh(self) -> None:
        try:
            discovered = await self.discover()
            self._tools = {t.name: t for t in discovered}
            self.info.tool_count = len(self._tools)
        except Exception:
            self.info.status = ProviderStatus.DEGRADED
            raise

    # ==================================================================
    # 子类实现
    # ==================================================================

    @abstractmethod
    async def discover(self) -> list[HavenTool]: ...

    @abstractmethod
    async def health_check(self) -> bool: ...

    async def _on_start(self) -> None:  # noqa: B027
        pass

    async def _on_stop(self) -> None:  # noqa: B027
        pass

    # ==================================================================
    # 工具访问
    # ==================================================================

    @property
    def tools(self) -> dict[str, HavenTool]:
        return self._tools

    def get_tool(self, name: str) -> HavenTool | None:
        return self._tools.get(name)

    def list_tools(self) -> list[HavenTool]:
        return list(self._tools.values())

    def filter_tools(
        self, *, category: str | None = None, tag: str | None = None
    ) -> list[HavenTool]:
        result = self.list_tools()
        if category:
            result = [t for t in result if t.metadata.category.value == category]
        if tag:
            result = [t for t in result if tag in t.metadata.tags]
        return result
