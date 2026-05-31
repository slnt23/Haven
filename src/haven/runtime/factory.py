"""AgentFactory V2 — 创建完整初始化的 PlannerAgent 系统。

与 V1 的 ``agents/factory.py`` 并行存在，V2 返回 PlannerAgent。
"""

from __future__ import annotations

import logging
from pathlib import Path

from haven.config import settings, find_user_path
from haven.runtime.runtime import AgentRuntime
from haven.runtime.planner import PlannerAgent
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
) -> PlannerAgent:
    """创建完整的 Haven V2 系统。

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
        _load_all_skills(runtime)

    # 3. LLM
    runtime.init_llm()

    # 4. MCP tools（后续 Provider 阶段增强）
    mcp_tools: dict = {}
    if load_mcp:
        mcp_tools = await _load_mcp(runtime)

    # 5. Tools（当前阶段: 注册内置工具 + MCP）
    _register_builtin_tools(runtime, mcp_tools)

    # 6. Planner
    planner = PlannerAgent(runtime)

    logger.info(
        "V2 system ready: planner + runtime with %d skills, %d tools",
        len(SkillRegistry.list_all()),
        len(runtime._tools),
    )
    return planner


# ==================================================================
# Skill 加载
# ==================================================================

def _load_all_skills(runtime: AgentRuntime) -> None:
    """加载系统人格 + 用户 skill 目录。注册到 SkillRegistry。"""
    # 系统人格
    if _SYSTEM_PERSONA.is_file():
        persona = SkillLoader.load_single(_SYSTEM_PERSONA)
        if persona is not None:
            SkillRegistry.register_instance(persona)
            logger.debug("System persona loaded: %s", persona.name)

    # 用户 skill 目录
    user_dir = find_user_path(settings.skill_directory)
    if user_dir.is_dir():
        loaded = SkillLoader.load_from_dir(user_dir)
        for skill in loaded:
            SkillRegistry.register_instance(skill)
        logger.debug("User skills loaded: %d skill(s)", len(loaded))


# ==================================================================
# 工具注册（过渡阶段，Provider 阶段会重构）
# ==================================================================

def _register_builtin_tools(runtime: AgentRuntime, mcp_tools: dict) -> None:
    """注册内置工具 + MCP 工具。激活全部工具。

    后续 Provider 模块会用 ToolManager 替代此方法。
    """
    from langchain_core.tools import StructuredTool

    # 内置工具
    _try_register(runtime, "code_exec", "haven.tools.code_exec", "CodeExecTool")
    _try_register(runtime, "file_ops", "haven.tools.file_ops", "FileOpsTool")
    _try_register(runtime, "web_search", "haven.tools.web_search", "WebSearchTool")
    _try_register(runtime, "rag_search", "haven.tools.rag_search", "RAGSearchTool")
    _try_register(runtime, "medical_kb", "haven.tools.medical", "MedicalKnowledgeTool")
    _try_register(runtime, "email", "haven.tools.email_tool", "EmailTool")

    # MCP 工具
    for name, tool in mcp_tools.items():
        runtime.register_tool(tool)

    runtime.activate_all_tools()
    runtime.bind_tools_to_llm()


def _try_register(
    runtime: AgentRuntime,
    name: str,
    module_path: str,
    class_name: str,
) -> None:
    """尝试导入内置工具类并注册。"""
    import importlib
    try:
        mod = importlib.import_module(module_path)
        cls = getattr(mod, class_name, None)
        if cls is None:
            return
        instance = cls()
        runtime.register_tool(instance)
        from langchain_core.tools import StructuredTool
        try:
            lc_tool = StructuredTool.from_function(
                coroutine=instance.__call__,
                name=getattr(instance, "name", name),
                description=getattr(instance, "description", ""),
            )
        except Exception:
            lc_tool = instance
        runtime.register_tool(lc_tool)
    except ImportError:
        pass
    except Exception:
        logger.debug("Failed to register tool '%s'", name, exc_info=True)


# ==================================================================
# MCP 加载（过渡阶段）
# ==================================================================

async def _load_mcp(runtime: AgentRuntime) -> dict:
    """加载 MCP 工具。返回 {name: BaseTool} 字典。"""
    if not settings.mcp_enabled:
        return {}

    try:
        from haven.mcp import MCPManager, MCPServerConfig
    except ImportError:
        logger.debug("MCP SDK not available")
        return {}

    from haven.config import get_mcp_config
    raw = get_mcp_config()
    if not raw:
        return {}

    configs = []
    for entry in raw:
        try:
            configs.append(MCPServerConfig(**entry))
        except Exception:
            continue

    configs = [c for c in configs if c.enabled]
    if not configs:
        return {}

    mcp_manager = MCPManager(configs)
    try:
        tools = await mcp_manager.start()
    except Exception as exc:
        logger.warning("MCP connection failed: %s", exc)
        return {}

    # 将 manager 挂到 runtime 上供后续使用
    runtime._mcp_manager = mcp_manager
    return tools
