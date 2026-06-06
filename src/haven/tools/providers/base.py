"""提供者抽象基类 —— 定义工具来源的标准接口和生命周期状态机。

每种工具来源（内置 / MCP / 自定义 API）实现一个 Provider。
ToolLoader 统一编排所有 Provider 的启动、停止、刷新。

状态机：
    UNINITIALIZED → CONNECTING → CONNECTED
                   → CONNECTING → DEGRADED   (refresh 失败)
                   → CONNECTING → ERROR      (start 异常)
    CONNECTED      → DISCONNECTED            (stop)
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum

from langchain_core.tools import BaseTool


class ProviderStatus(str, Enum):
    """Provider 状态枚举。"""
    UNINITIALIZED = "uninitialized"  # 尚未启动
    CONNECTING = "connecting"  # 正在连接
    CONNECTED = "connected"  # 已连接，正常
    DEGRADED = "degraded"  # 部分可用（refresh 失败）
    DISCONNECTED = "disconnected"  # 已断开
    ERROR = "error"  # 连接失败


@dataclass
class ProviderInfo:
    """Provider 描述信息，由 ToolLoader 读取用于状态展示。"""
    name: str  # 唯一名称
    type: str = "custom"  # 类型标签：builtin / mcp / custom
    description: str = ""  # 人类可读描述
    version: str = "1.0"  # Provider 版本
    tool_count: int = 0  # 当前发现的工具数量
    status: ProviderStatus = ProviderStatus.UNINITIALIZED  # 当前状态
    last_error: str = ""  # 最近一次错误信息


class ToolProvider(ABC):
    """工具提供者抽象基类。

    子类必须实现：
      - discover()      — 发现工具，返回 list[BaseTool]
      - health_check()  — 健康检查，返回 bool

    可选覆盖（钩子）：
      - _on_start()     — 初始化连接
      - _on_stop()      — 释放资源

    start / stop / refresh 是模板方法，子类不应覆盖。
    """

    def __init__(self, name: str, provider_type: str = "custom") -> None:
        self.info = ProviderInfo(name=name, type=provider_type)  # 公开信息
        self._tools: dict[str, BaseTool] = {}  # 内部工具缓存

    # ------------------------------------------------------------------
    # 生命周期（模板方法，子类不应覆盖）
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """启动 Provider：连接 → 发现工具 → 标记为 CONNECTED。"""
        self.info.status = ProviderStatus.CONNECTING
        try:
            await self._on_start()  # 子类钩子：建立连接
            await self.refresh()  # 发现工具
            self.info.status = ProviderStatus.CONNECTED
        except Exception as exc:
            self.info.status = ProviderStatus.ERROR
            self.info.last_error = str(exc)
            raise

    async def stop(self) -> None:
        """停止 Provider：释放资源 → 清空工具 → 标记为 DISCONNECTED。"""
        try:
            await self._on_stop()  # 子类钩子：释放连接
        finally:
            self.info.status = ProviderStatus.DISCONNECTED
            self._tools.clear()

    async def refresh(self) -> None:
        """刷新工具列表：重新 discover()，更新内部缓存。"""
        try:
            discovered = await self.discover()
            self._tools = {t.name: t for t in discovered}  # 按名称索引
            self.info.tool_count = len(self._tools)
        except Exception:
            self.info.status = ProviderStatus.DEGRADED  # 刷新失败，降级运行
            raise

    # ------------------------------------------------------------------
    # 子类契约
    # ------------------------------------------------------------------

    @abstractmethod
    async def discover(self) -> list[BaseTool]:
        """发现该 Provider 提供的全部工具。子类必须实现。"""
        ...

    @abstractmethod
    async def health_check(self) -> bool:
        """检查 Provider 是否可用。子类必须实现。"""
        ...

    async def _on_start(self) -> None:
        """启动钩子：子类可在此建立连接、初始化资源。"""
        pass

    async def _on_stop(self) -> None:
        """停止钩子：子类可在此释放连接、清理资源。"""
        pass

    # ------------------------------------------------------------------
    # 工具访问
    # ------------------------------------------------------------------

    def get_tool(self, name: str) -> BaseTool | None:
        """按名称获取单个工具。"""
        return self._tools.get(name)

    def list_tools(self) -> list[BaseTool]:
        """获取该 Provider 当前的全部工具列表。"""
        return list(self._tools.values())
