"""AgentFactory V3 — 中间件管道 + ToolManager + Provider 架构装配系统。"""

from __future__ import annotations

import logging
from pathlib import Path

from haven.config import find_user_path, settings
from haven.middleware import MiddlewarePipeline
from haven.middleware.filesystem import FilesystemMiddleware
from haven.middleware.memory import MemoryMiddleware
from haven.middleware.personality import PersonalityMiddleware
from haven.middleware.skills import SkillsMiddleware
from haven.middleware.summarization import SummarizationMiddleware
from haven.runtime.planner import PlannerAgent
from haven.runtime.runtime import AgentRuntime
from haven.skills.loader import SkillLoader
from haven.skills.registry import SkillRegistry

logger = logging.getLogger("haven.factory")

_SYSTEM_PERSONA = Path(__file__).resolve().parent.parent / "config" / "haven.md"


async def create_agent(
    session_id: str = "default",
    entity_name: str = "user",
    channel: str = "default",
    *,
    load_skills: bool = True,
    load_mcp: bool = True,
    middlewares: list | None = None,
) -> PlannerAgent:
    """创建完整的 Haven V3 系统。

    Returns:
        PlannerAgent — ``planner.execute(task)`` 为唯一入口。
    """
    # 1. Runtime
    runtime = AgentRuntime()
    runtime.memory.session_id = session_id
    runtime.memory.entity_name = entity_name
    runtime.memory.channel = channel
    runtime.state.session_id = session_id
    runtime.state.entity_name = entity_name
    runtime.state.channel = channel

    # 2. Skills
    if load_skills:
        _load_all_skills()

    # 3. LLM
    runtime.init_llm()

    # 4. ToolManager + Providers
    await _init_tools(runtime, load_mcp)

    # 5. WorkflowRegistry
    from haven.workflows.registry import WorkflowRegistry

    # 6. Middleware Pipeline
    if middlewares is None:
        # 加载系统人格 prompt
        persona_prompt = ""
        if _SYSTEM_PERSONA.is_file():
            persona_prompt = _SYSTEM_PERSONA.read_text(encoding="utf-8")

        pipeline = MiddlewarePipeline([
            PersonalityMiddleware(skill_prompt=persona_prompt),
            MemoryMiddleware(manager=runtime.memory),
            SummarizationMiddleware(model=runtime.llm, max_tokens=8000),
            FilesystemMiddleware(workspace=settings.project_root),
            SkillsMiddleware(),
        ])
    else:
        pipeline = MiddlewarePipeline(middlewares)

    runtime._pipeline = pipeline

    # 7. Planner
    planner = PlannerAgent(runtime, workflow_registry=WorkflowRegistry)

    logger.info(
        "V3 system ready: %d skills, %d tools, %d workflows",
        len(SkillRegistry.list_all()),
        len(runtime._tools),
        len(WorkflowRegistry.list_all()),
    )
    return planner


# ==================================================================
# Skill 加载
# ==================================================================


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


async def _init_tools(runtime: AgentRuntime, load_mcp: bool) -> None:
    from haven.tools.manager import ToolManager
    from haven.tools.providers.builtin import BuiltinProvider

    tm = ToolManager()

    # 内置工具
    tm.add_provider(BuiltinProvider())

    # MCP 工具
    if load_mcp and settings.mcp_enabled:
        mcp_configs = _load_mcp_configs()
        if mcp_configs:
            from haven.tools.providers.mcp import MCPProvider

            for cfg in mcp_configs:
                tm.add_provider(MCPProvider(cfg))

    await tm.start_all()

    # 同步到 Runtime
    runtime._tool_manager = tm
    for tool in tm.list_all():
        runtime.register_tool(tool)

    # ToolResolver
    from haven.tools.resolver import ToolResolver

    runtime._tool_resolver = ToolResolver(tm)
    logger.info("ToolResolver: initialized with %d tools", len(tm.list_all()))

    runtime.activate_all_tools()
    logger.info(
        "ToolManager: %d tools from %d provider(s)", len(tm.list_all()), len(tm.list_providers())
    )


def _load_mcp_configs() -> list:
    """从 mcp.json 加载启用的 MCP 服务器配置。"""
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
