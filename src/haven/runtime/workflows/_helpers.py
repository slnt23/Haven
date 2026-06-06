"""工作流节点共享辅助函数。

每个工作流节点通过此模块获取 Agent、构建上下文、执行推理。
不涉及 Tool 解析 —— 工具已在 Agent 创建时绑定。
"""

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
    """构建上下文并执行 Agent（工作流节点统一入口）。

    Dispatcher 负责构建 system_prompt，Agent 负责执行。
    节点不直接操作工具或上下文。
    """
    cfg = config["configurable"]
    rt = get_agent(config, agent_type)
    dispatcher = cfg.get("dispatcher")
    effective_task = task or prompt[:500]
    names = list(skill_names or [])

    # 正常路径：通过 Dispatcher 构建上下文
    if dispatcher is not None:
        system_prompt = await dispatcher.prepare_agent(rt, names, task=effective_task)
        return await rt.run(prompt, system_prompt=system_prompt)

    # 回退路径：Dispatcher 不可用时直接用 ContextBuilder
    context_builder = cfg.get("context_builder")
    if context_builder is not None:
        skills = resolve_skills(names)
        ctx = context_builder.build(
            agent_prompt=getattr(rt, "agent_prompt", ""),
            skills=skills,
            task=effective_task,
        )
        return await rt.run(prompt, system_prompt=ctx.system_prompt)

    # 最终回退：无上下文直接执行
    return await rt.run(prompt)


def resolve_skills(names: list[str]) -> list[Any]:
    """将 skill 名称列表解析为 Skill 对象列表。"""
    from haven.skills.registry import SkillRegistry

    skills: list[Any] = []
    for name in names:
        try:
            skills.append(SkillRegistry.get(name))
        except KeyError:
            pass
    return skills
