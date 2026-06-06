"""CoordinatorFactory — ContextBuilder + 多专业 Agent + Coordinator 装配系统。"""

from __future__ import annotations

import aiosqlite
import logging
from pathlib import Path
from typing import Any

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from haven.config import find_user_path, settings
from haven.core.llm import create_llm
from haven.core.state import RuntimeState
from haven.runtime.agents.base import BaseAgent
from haven.runtime.context import ContextBuilder
from haven.runtime.coordinator import Coordinator
from haven.skills.loader import SkillLoader
from haven.skills.registry import SkillRegistry

logger = logging.getLogger("haven.factory")

# 空 tools 列表时的默认工具（不再绑定全部工具）
_DEFAULT_AGENT_TOOLS = ["web_search"]


async def create_coordinator(
    session_id: str = "default",
    entity_name: str = "user",
    channel: str = "default",
    *,
    load_skills: bool = True,
    load_mcp: bool = True,
    use_memory: bool | None = None,
) -> Coordinator:
    """创建完整的 Haven 多智能体系统。

    Returns:
        Coordinator — ``coordinator.execute(task)`` 为唯一入口。
    """
    state = RuntimeState()
    state.session_id = session_id
    state.entity_name = entity_name
    state.channel = channel

    # 1. Skills
    if load_skills:
        _load_all_skills()

    # 2. LLM
    llm = create_llm()

    # 3. ToolManager + Providers
    tool_registry, tool_manager = await _init_tools(load_mcp)

    # 4. Shared Checkpointer
    db_dir = Path.cwd() / ".data"
    db_dir.mkdir(parents=True, exist_ok=True)
    conn = await aiosqlite.connect(str(db_dir / "checkpoint.db"))
    checkpointer = AsyncSqliteSaver(conn)
    await checkpointer.setup()

    # 5. ContextBuilder + ToolResolver + FactStore
    context_builder = ContextBuilder()
    from haven.tools.resolver import ToolResolver

    tool_resolver = ToolResolver(tool_manager)

    memory_on = settings.memory_enabled if use_memory is None else use_memory
    fact_store = None
    if memory_on:
        from haven.memory.fact_store import FactStore

        memory_path = Path.cwd() / settings.memory_db_path
        fact_store = FactStore(memory_path)

    # 6. Create Agents
    agent_defs = _load_agent_definitions()
    _validate_agent_config(agent_defs, tool_registry)

    agents: dict[str, BaseAgent] = {}
    for name, ad in agent_defs.items():
        tool_names = ad.get("tools", [])
        if not tool_names:
            tool_names = list(_DEFAULT_AGENT_TOOLS)
        agent_tools = [t for t in tool_registry.values() if t.name in tool_names]
        agents[name] = BaseAgent(
            name=name,
            llm=llm,
            tools=agent_tools,
            checkpointer=checkpointer,
            state=state,
            agent_prompt=ad.get("prompt", ""),
            default_skills=ad.get("skills", []),
        )

    # 7. 注册预定义工作流（side-effect import）
    from haven.runtime.graphs import dev, diagnosis, research  # noqa: F401
    from haven.runtime.registry import WorkflowRegistry

    # 8. Coordinator
    coordinator = Coordinator(
        agents=agents,
        llm=llm,
        workflow_registry=WorkflowRegistry,
        state=state,
        context_builder=context_builder,
        tool_resolver=tool_resolver,
        fact_store=fact_store,
        checkpointer=checkpointer,
        use_memory=memory_on,
    )
    coordinator.tool_manager = tool_manager

    logger.info(
        "Coordinator ready: %d agents, %d skills, %d workflows",
        len(agents),
        len(SkillRegistry.list_all()),
        len(WorkflowRegistry.list_all()),
    )
    return coordinator


def _load_agent_definitions() -> dict:
    """从 haven.yaml 加载 Agent 定义。"""
    from omegaconf import OmegaConf

    path = Path(__file__).resolve().parent.parent / "config" / "haven.yaml"
    config = OmegaConf.load(path)
    # 用户覆盖
    user_path = Path.cwd() / "haven.yaml"
    if user_path.is_file():
        config = OmegaConf.merge(config, OmegaConf.load(user_path))

    agents_cfg = config.get("agents", {})
    if hasattr(agents_cfg, "items"):
        return {k: dict(v) for k, v in agents_cfg.items()}
    return dict(agents_cfg)


def _validate_agent_config(agent_defs: dict, tool_registry: dict) -> None:
    """启动时校验 Agent 配置与已加载资源的一致性。"""
    available_tools = set(tool_registry.keys())
    available_skills = set(SkillRegistry.list_all().keys())

    for name, ad in agent_defs.items():
        tool_names = ad.get("tools", [])
        if tool_names:
            missing = set(tool_names) - available_tools
            if missing:
                logger.warning("Agent '%s' 引用了不存在的工具: %s", name, sorted(missing))

        for skill_name in ad.get("skills", []):
            if skill_name not in available_skills:
                logger.warning("Agent '%s' 引用了不存在的 skill: %s", name, skill_name)


# ==================================================================
# Skill 加载
# ==================================================================

_SYSTEM_PERSONA = Path(__file__).resolve().parent.parent / "config" / "haven.md"


def _load_all_skills() -> None:
    if _SYSTEM_PERSONA.is_file():
        persona = SkillLoader.load_single(_SYSTEM_PERSONA)
        if persona is not None:
            SkillRegistry.register_instance(persona)

    user_dir = find_user_path(settings.skill_directory)
    if user_dir.is_dir():
        for skill in SkillLoader.load_from_dir(user_dir):
            SkillRegistry.register_instance(skill)


# ==================================================================
# ToolManager + Provider 初始化
# ==================================================================


async def _init_tools(load_mcp: bool) -> tuple[dict[str, Any], Any]:
    from haven.tools.manager import ToolManager
    from haven.tools.providers.builtin import BuiltinProvider

    tm = ToolManager()
    tm.add_provider(BuiltinProvider())

    if load_mcp and settings.mcp_enabled:
        mcp_configs = _load_mcp_configs()
        if mcp_configs:
            from haven.tools.providers.mcp import MCPProvider

            for cfg in mcp_configs:
                tm.add_provider(MCPProvider(cfg))

    await tm.start_all()

    tools = {t.name: t for t in tm.list_all()}
    logger.info("ToolManager: %d tools from %d provider(s)", len(tools), len(tm.list_providers()))
    return tools, tm


def _load_mcp_configs() -> list:
    from haven.config import get_mcp_config
    from haven.config.mcp import MCPServerConfig

    raw = get_mcp_config()
    configs = []
    for entry in raw:
        try:
            cfg = MCPServerConfig(**entry)
            if cfg.enabled:
                configs.append(cfg)
        except Exception:
            continue
    return configs
