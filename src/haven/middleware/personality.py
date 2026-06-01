"""系统人格中间件 — 注入系统人格 prompt。"""

from __future__ import annotations

from typing import Any

from haven.middleware.base import Middleware


class PersonalityMiddleware(Middleware):
    """将系统人格 prompt 注入 state['system_prompt']。"""

    def __init__(self, skill_prompt: str = ""):
        self._skill_prompt = skill_prompt

    async def before_agent(self, state: dict[str, Any]) -> dict[str, Any]:
        if self._skill_prompt:
            existing = state.get("system_prompt", "")
            state["system_prompt"] = (
                f"{self._skill_prompt}\n\n{existing}" if existing else self._skill_prompt
            )
        return state
