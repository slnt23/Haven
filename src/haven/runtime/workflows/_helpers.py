"""工作流节点共享辅助函数。

每个工作流节点通过此模块获取 Agent、构建上下文、执行推理。
不涉及 Tool 解析 —— 工具已在 Agent 创建时绑定。

Skills 动态解析：节点通过 skill_tags 声明意图，系统按标签匹配
已注册 skill，与 Coordinator 选中的 plan_skills 取并集。
"""

from __future__ import annotations

import uuid
from typing import Any

from haven.capability.registry import CapabilityRegistry


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
    skill_tags: list[str] | None = None,
    state: dict[str, Any] | None = None,
    agent_type: str = "general",
    task: str = "",
) -> str:
    """构建上下文并执行 Agent（工作流节点统一入口）。

    Skills 动态解析：
      1. 从 workflow state 读取 Coordinator 选中的 plan_skills
      2. 按 skill_tags 进行标签交集匹配
      3. 取并集后统一做依赖解析

    每个节点使用独立的 thread_id，避免不同节点的对话历史串扰。
    """
    cfg = config["configurable"]
    rt = get_agent(config, agent_type)
    dispatcher = cfg.get("dispatcher")
    effective_task = task or prompt[:500]

    # ---- 动态 skill 解析 ------------------------------------------------
    plan_skills: list[str] = []
    if state:
        plan_skills = list(state.get("plan_skills", []))

    tag_matched: list[str] = []
    if skill_tags:
        dispatcher_obj = cfg.get("dispatcher")
        cap_registry = getattr(dispatcher_obj, "_capability", None) if dispatcher_obj else None
        if cap_registry is not None:
            tag_matched = cap_registry.resolve_by_tags(list(skill_tags))

    # 并集：plan_skills + tag_matched
    names = list(set(plan_skills) | set(tag_matched))
    # --------------------------------------------------------------------

    # 每个节点独立的 thread_id，防止 ReAct 历史跨节点污染
    node_thread = str(uuid.uuid4())

    # 正常路径：通过 Dispatcher 构建上下文
    if dispatcher is not None:
        system_prompt = await dispatcher.prepare_agent(rt, names, task=effective_task)
        return await rt.run(prompt, system_prompt=system_prompt, thread_id=node_thread)

    # 回退路径：Dispatcher 不可用时直接用 ContextBuilder
    context_builder = cfg.get("context_builder")
    if context_builder is not None:
        cap_registry = getattr(dispatcher_obj, "_capability", None) if dispatcher_obj else None
        skills = _resolve_skills(cap_registry, names)
        ctx = context_builder.build(
            agent_prompt=getattr(rt, "agent_prompt", ""),
            skills=skills,
            task=effective_task,
        )
        return await rt.run(prompt, system_prompt=ctx.system_prompt, thread_id=node_thread)

    # 最终回退：无上下文直接执行
    return await rt.run(prompt, thread_id=node_thread)


def _resolve_skills(registry: CapabilityRegistry | None, names: list[str]) -> list[Any]:
    """将 skill 名称列表解析为 Skill 对象列表，含依赖解析。"""
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
