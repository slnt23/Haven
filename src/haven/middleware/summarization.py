"""摘要中间件 — 基于 token 预算的对话历史压缩。

使用 llm.get_num_tokens() 做精确 token 计数，超限时裁剪最早的消息。
"""

from __future__ import annotations

from typing import Any

from haven.middleware.base import Middleware


class SummarizationMiddleware(Middleware):
    """评估消息 token 占用，超限时裁剪对话历史。"""

    def __init__(self, model: Any = None, max_tokens: int = 8000):
        self._model = model
        self._max_tokens = max_tokens

    async def before_agent(self, state: dict[str, Any]) -> dict[str, Any]:
        messages = state.get("messages", [])
        if self._model is None or not messages:
            return state

        total = sum(
            self._model.get_num_tokens(getattr(m, "content", "") or "")
            for m in messages
        )
        if total <= self._max_tokens:
            return state

        cutoff = total - self._max_tokens
        while messages and cutoff > 0:
            first = messages[0]
            tk = self._model.get_num_tokens(getattr(first, "content", "") or "")
            messages.pop(0)
            cutoff -= tk

        state["messages"] = messages
        return state
