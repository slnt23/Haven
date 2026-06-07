"""Middleware 基类。

每个中间件在 agent 调用前后修改 state dict。
管道按注册顺序执行 before_agent，逆序执行 after_agent。
"""

from __future__ import annotations

from typing import Any


class Middleware:
    """中间件基类。"""

    async def before_agent(self, state: dict[str, Any]) -> dict[str, Any]:
        """在 agent 调用前修改 state。"""
        return state

    async def after_agent(self, state: dict[str, Any]) -> dict[str, Any]:
        """在 agent 调用后修改 state。"""
        return state
