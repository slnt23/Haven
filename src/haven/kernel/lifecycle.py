"""生命周期管理 —— 进程级 startup / shutdown 钩子。

组件实现 LifecycleHook，向 LifecycleManager 注册。
启动时按注册顺序执行 on_startup，关闭时逆序执行 on_shutdown。
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod

logger = logging.getLogger("haven.kernel.lifecycle")


class LifecycleHook(ABC):
    """生命周期钩子抽象。

    实现此接口并注册到 LifecycleManager，即可参与进程级启停流程。
    """

    @abstractmethod
    async def on_startup(self) -> None:
        """组件初始化逻辑。"""
        ...

    @abstractmethod
    async def on_shutdown(self) -> None:
        """组件清理逻辑（释放连接、停止任务等）。"""
        ...


class LifecycleManager:
    """进程生命周期管理器。

    持有有序的 LifecycleHook 列表。
    启动时顺序执行，关闭时逆序执行，保证依赖关系正确。

    Usage::

        manager = LifecycleManager()
        manager.register(my_component)

        await manager.startup()   # 启动所有组件
        ...
        await manager.shutdown()  # 逆序关闭
    """

    def __init__(self) -> None:
        self._hooks: list[LifecycleHook] = []

    def register(self, hook: LifecycleHook) -> None:
        """注册生命周期钩子。按注册顺序执行 on_startup。"""
        self._hooks.append(hook)

    async def startup(self) -> None:
        """顺序执行所有钩子的 on_startup。

        单个钩子失败会记录异常但继续执行后续钩子，
        确保部分故障不影响整体启动。
        """
        for hook in self._hooks:
            name = type(hook).__name__
            logger.info("Starting: %s", name)
            try:
                await hook.on_startup()
            except Exception as exc:
                logger.error("Startup hook '%s' failed: %s", name, exc)

    async def shutdown(self) -> None:
        """逆序执行所有钩子的 on_shutdown。

        逆序保证后注册的组件先关闭（先注册 = 更底层）。
        每个钩子失败不影响其他。
        """
        for hook in reversed(self._hooks):
            name = type(hook).__name__
            logger.info("Shutting down: %s", name)
            try:
                await hook.on_shutdown()
            except Exception as exc:
                logger.error("Shutdown hook '%s' failed: %s", name, exc)
