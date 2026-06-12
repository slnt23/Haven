"""ToolProvider ABC —— 工具来源的抽象基类与生命周期状态机。

每种工具来源（内置 / MCP / 自定义）实现一个 Provider。
CapabilityLoader 统一编排所有 Provider 的启动、停止、刷新。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum

from langchain_core.tools import BaseTool


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

    子类必须实现:
      - discover()      — 发现工具，返回 list[BaseTool]
      - health_check()  — 健康检查，返回 bool

    可选覆盖（钩子）:
      - _on_start()     — 初始化连接
      - _on_stop()      — 释放资源
    """

    def __init__(self, name: str, provider_type: str = "custom") -> None:
        self.info = ProviderInfo(name=name, type=provider_type)
        self._tools: dict[str, BaseTool] = {}

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

    @abstractmethod
    async def discover(self) -> list[BaseTool]:
        ...

    @abstractmethod
    async def health_check(self) -> bool:
        ...

    async def _on_start(self) -> None:
        pass

    async def _on_stop(self) -> None:
        pass

    def get_tool(self, name: str) -> BaseTool | None:
        return self._tools.get(name)

    def list_tools(self) -> list[BaseTool]:
        return list(self._tools.values())
