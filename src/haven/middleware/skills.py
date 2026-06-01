"""领域 Skill 中间件 — 注入 Planner 激活的领域 skill prompt。

从 state["active_skills"] 读取技能名列表，从 SkillRegistry 加载并注入 prompt。
"""

from __future__ import annotations

from typing import Any

from haven.middleware.base import Middleware


class SkillsMiddleware(Middleware):
    """从 state['active_skills'] 读取激活技能，注入其 prompt 到 system_prompt。"""

    async def before_agent(self, state: dict[str, Any]) -> dict[str, Any]:
        skill_names: list[str] = state.get("active_skills", [])
        if not skill_names:
            return state

        from haven.skills.registry import SkillRegistry

        parts: list[str] = []
        for name in skill_names:
            try:
                skill = SkillRegistry.get(name)
                prompt = getattr(skill, "prompt_extension", "") or getattr(skill, "prompt", "")
                if prompt.strip():
                    parts.append(prompt.strip())
            except KeyError:
                pass

        if parts:
            skill_text = "\n\n".join(parts)
            existing = state.get("system_prompt", "")
            state["system_prompt"] = f"{existing}\n\n{skill_text}" if existing else skill_text

        return state
