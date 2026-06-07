"""中间件管道编排。

按顺序执行 before_agent，逆序执行 after_agent。
"""

from __future__ import annotations

from typing import Any

from .base import Middleware


class MiddlewarePipeline:
    """中间件管道。

    用法::

        pipeline = MiddlewarePipeline([
            PersonalityMiddleware(skill="haven.md"),
            MemoryMiddleware(manager=mm),
        ])
        state = await pipeline.before(state)
        state = await agent.ainvoke(state)
        state = await pipeline.after(state)
    """

    def __init__(self, middlewares: list[Middleware]):
        self._middlewares = middlewares

    async def before(self, state: dict[str, Any]) -> dict[str, Any]:
        for mw in self._middlewares:
            state = await mw.before_agent(state)
        return state

    async def after(self, state: dict[str, Any]) -> dict[str, Any]:
        for mw in reversed(self._middlewares):
            state = await mw.after_agent(state)
        return state
