"""工作流节点共享辅助函数。"""

from __future__ import annotations

import uuid
from typing import Any

from langgraph.checkpoint.memory import MemorySaver

from haven.capability.registry import CapabilityRegistry


def create_checkpointer() -> MemorySaver:
    """创建内存 checkpointer。"""
    return MemorySaver()


def get_agent(config: dict[str, Any], prefer: str = "general") -> Any:
    """从 configurable 中选取专业 Agent。"""
    cfg = config.get("configurable", {})
    agents = cfg.get("agents", {})
    if prefer in agents:
        return agents[prefer]
    return cfg["agent"]


async def run_agent_node(
    config: dict[str, Any],
    prompt: str,
    *,
    skill_tags: list[str] | None = None,
    state: dict[str, Any] | None = None,
    agent_type: str = "general",
    task: str = "",
) -> str:
    """构建上下文并执行 Agent（工作流节点统一入口）。"""
    cfg = config["configurable"]
    rt = get_agent(config, agent_type)
    dispatcher = cfg.get("dispatcher")
    effective_task = task or prompt[:500]

    # 动态 skill 解析
    plan_skills: list[str] = []
    if state:
        plan_skills = list(state.get("plan_skills", []))

    tag_matched: list[str] = []
    if skill_tags:
        cap_registry = getattr(dispatcher, "_capability", None) if dispatcher else None
        if cap_registry is not None:
            tag_matched = cap_registry.resolve_by_tags(list(skill_tags))

    names = list(set(plan_skills) | set(tag_matched))
    node_thread = str(uuid.uuid4())

    if dispatcher is not None:
        system_prompt = await dispatcher._prepare(rt, names, _dummy_session(), task=effective_task)
        return await rt.run(prompt, system_prompt=system_prompt, thread_id=node_thread)

    # 回退路径
    context_builder = cfg.get("context_builder")
    if context_builder is not None:
        skills = _resolve_skills(cap_registry, names)
        ctx = context_builder.build(
            agent_prompt=getattr(rt, "agent_prompt", ""),
            skills=skills,
            task=effective_task,
        )
        return await rt.run(prompt, system_prompt=ctx.system_prompt, thread_id=node_thread)

    return await rt.run(prompt, thread_id=node_thread)


def _dummy_session() -> Any:
    from haven.session.models import Session
    return Session(id="workflow-node")


def _resolve_skills(registry: CapabilityRegistry | None, names: list[str]) -> list[Any]:
    if registry is None:
        return []
    from haven.capability.resolver import DependencyResolver
    resolved = DependencyResolver.resolve(list(names), registry)
    skills: list[Any] = []
    for name in resolved:
        try:
            skills.append(registry.get_skill(name))
        except KeyError:
            pass
    return skills
