from __future__ import annotations

from abc import ABC, abstractmethod

from haven.core.base_agent import BaseAgent


class BaseChannel(ABC):
    """聊天通道抽象接口。

    通道是消息的入口/出口——接收传入消息，通过共享 Agent 处理，返回响应。
    """

    def __init__(self, name: str, enabled: bool = True) -> None:
        self.name = name
        self.enabled = enabled
        self._agent: BaseAgent | None = None

    @property
    def agent(self) -> BaseAgent:
        if self._agent is None:
            raise RuntimeError(f"Channel '{self.name}': agent not set")
        return self._agent

    async def handle_message(self, message: str) -> str:
        """将消息路由到共享 agent 并返回响应。"""
        return await self.agent.run(message)

    @abstractmethod
    async def start(self, agent: BaseAgent) -> None:
        """用共享 agent 实例启动通道。"""
        self._agent = agent

    @property
    def status_detail(self) -> str:
        """守护进程启动 banner 中显示的单行描述。可覆写以显示通道特定信息（地址、app-id 等）。"""
        return ""

    @abstractmethod
    async def stop(self) -> None:
        """停止通道并释放资源。"""
