"""记忆中间件 — 四层记忆检索注入。"""

from __future__ import annotations

from typing import Any

from haven.middleware.base import Middleware


class MemoryMiddleware(Middleware):
    """调用 MemoryManager.retrieve() 四路并行检索，结果注入 state['system_prompt']。

    取代 ContextManager._collect_memory() 的单表 SQL 查询。
    """

    def __init__(self, manager: Any = None):
        self._manager = manager

    def set_manager(self, manager: Any) -> None:
        self._manager = manager

    async def before_agent(self, state: dict[str, Any]) -> dict[str, Any]:
        if self._manager is None:
            return state

        task = state.get("task", "")
        try:
            ctx = await self._manager.retrieve(task=task)
            memory_text = ctx.format_for_prompt()
        except Exception:
            return state

        if memory_text and memory_text.strip():
            existing = state.get("system_prompt", "")
            state["system_prompt"] = f"{existing}\n\n{memory_text}" if existing else memory_text

        return state
