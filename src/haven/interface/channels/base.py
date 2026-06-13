"""消息通道抽象接口。

通道是消息的入口/出口——接收传入消息，通过共享 Runtime 处理，返回响应。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class BaseChannel(ABC):
    """聊天通道抽象基类。

    每个 Channel 共享同一个 Runtime 实例。
    通过 Runtime.execute() 处理消息。
    """

    def __init__(self, name: str, enabled: bool = True) -> None:
        self.name = name
        self.enabled = enabled
        self._runtime: Any = None

    @property
    def runtime(self) -> Any:
        """共享的 Runtime 实例（Executor + Agents + Tools）。"""
        if self._runtime is None:
            raise RuntimeError(f"Channel '{self.name}': runtime not set")
        return self._runtime

    async def handle_message(self, message: str) -> str:
        """将消息路由到 Runtime 并返回响应。"""
        return await self.runtime.execute(message)

    @abstractmethod
    async def start(self, runtime: Any) -> None:
        """用共享 Runtime 实例启动通道。"""
        self._runtime = runtime

    @property
    def status_detail(self) -> str:
        """守护进程启动 banner 中显示的单行描述。"""
        return ""

    @abstractmethod
    async def stop(self) -> None:
        """停止通道并释放资源。"""
