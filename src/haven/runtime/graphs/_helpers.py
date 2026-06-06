"""工作流节点共享辅助函数。"""

from __future__ import annotations

from typing import Any


def get_agent(config: dict[str, Any], prefer: str = "general") -> Any:
    """从 configurable 中选取专业 Agent，回退到默认 agent。"""
    cfg = config.get("configurable", {})
    agents = cfg.get("agents", {})
    if prefer in agents:
        return agents[prefer]
    return cfg["agent"]


async def run_agent_node(
    config: dict[str, Any],
    prompt: str,
    *,
    skill_names: list[str] | None = None,
    agent_type: str = "general",
    task: str = "",
) -> str:
    """构建上下文、绑定工具并执行 Agent（工作流节点统一入口）。"""
    cfg = config["configurable"]
    rt = get_agent(config, agent_type)
    coordinator = cfg.get("coordinator")
    effective_task = task or prompt[:500]
    names = list(skill_names or [])

    if coordinator is not None:
        system_prompt = await coordinator.prepare_agent(rt, names, task=effective_task)
        return await rt.run(prompt, system_prompt=system_prompt)

    # 回退：无 Coordinator 时仅构建 prompt（不应出现在正常路径）
    context_builder = cfg["context_builder"]
    skills = resolve_skills(names)
    ctx = context_builder.build(
        agent_prompt=getattr(rt, "agent_prompt", ""),
        skills=skills,
        task=effective_task,
    )
    return await rt.run(prompt, system_prompt=ctx.system_prompt)


def resolve_skills(names: list[str]) -> list[Any]:
    from haven.skills.registry import SkillRegistry

    skills: list[Any] = []
    for name in names:
        try:
            skills.append(SkillRegistry.get(name))
        except KeyError:
            pass
    return skills
