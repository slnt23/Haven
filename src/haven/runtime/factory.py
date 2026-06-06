"""CoordinatorFactory — ContextBuilder + 多专业 Agent + Coordinator 装配系统。"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

from langgraph.checkpoint.sqlite import SqliteSaver

from haven.config import find_user_path, settings
from haven.core.llm import create_llm
from haven.core.state import RuntimeState
from haven.runtime.agents.base import BaseAgent
from haven.runtime.context import ContextBuilder
from haven.runtime.coordinator import Coordinator
from haven.skills.loader import SkillLoader
from haven.skills.registry import SkillRegistry

logger = logging.getLogger("haven.factory")


async def create_coordinator(
    session_id: str = "default",
    entity_name: str = "user",
    channel: str = "default",
    *,
    load_skills: bool = True,
    load_mcp: bool = True,
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
    conn = sqlite3.connect(str(db_dir / "checkpoint.db"), check_same_thread=False)
    checkpointer = SqliteSaver(conn)
    checkpointer.setup()

    # 5. ContextBuilder
    context_builder = ContextBuilder()

    # 6. Create Agents
    agent_defs = _load_agent_definitions()
    agents: dict[str, BaseAgent] = {}
    for name, ad in agent_defs.items():
        tool_names = ad.get("tools", [])
        agent_tools = (
            [t for t in tool_registry.values() if t.name in tool_names]
            if tool_names else list(tool_registry.values())
        )
        agents[name] = BaseAgent(
            name=name,
            llm=llm,
            tools=agent_tools,
            checkpointer=checkpointer,
            state=state,
            agent_prompt=ad.get("prompt", ""),
        )

    # 7. WorkflowRegistry
    from haven.runtime.registry import WorkflowRegistry

    # 8. Coordinator
    coordinator = Coordinator(
        agents=agents,
        llm=llm,
        workflow_registry=WorkflowRegistry,
        state=state,
    )
    coordinator.tool_manager = tool_manager  # 供 daemon 清理

    logger.info(
        "Coordinator ready: %d agents, %d skills, %d workflows",
        len(agents),
        len(SkillRegistry.list_all()),
        len(WorkflowRegistry.list_all()),
    )
    return coordinator


def _load_agent_definitions() -> dict:
    """从 app.yaml 加载 Agent 定义。"""
    from omegaconf import OmegaConf

    path = Path(__file__).resolve().parent.parent / "config" / "app.yaml"
    config = OmegaConf.load(path)
    # 用户覆盖
    user_path = Path.cwd() / "haven.yaml"
    if user_path.is_file():
        config = OmegaConf.merge(config, OmegaConf.load(user_path))

    agents_cfg = config.get("agents", {})
    if hasattr(agents_cfg, "items"):
        return {k: dict(v) for k, v in agents_cfg.items()}
    return dict(agents_cfg)


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


async def _init_tools(load_mcp: bool) -> tuple[dict, Any]:
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
    from haven.tools.mcp_config import MCPServerConfig

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
