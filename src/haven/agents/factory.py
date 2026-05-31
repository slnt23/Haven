"""AgentFactory — 创建完整初始化的多 agent 系统。

返回一个 :class:`OrchestratorAgent`，已预注册 specialist 子 agent 并绑定工具。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from haven.config import settings, get_mcp_config, find_user_path
from haven.core.base_agent import BaseAgent
from haven.skills.loader import SkillLoader
from haven.agents.orchestrator import OrchestratorAgent
from haven.agents.coder import CoderAgent
from haven.agents.medical import MedicalAgent
from haven.agents.companion import CompanionAgent
from haven.agents.practical import PracticalAgent

logger = logging.getLogger("haven.factory")

_SYSTEM_PERSONA = Path(__file__).resolve().parent.parent / "config" / "haven.md"


async def create_agent(
    session_id: str = "default",
    entity_name: str = "user",
    channel: str = "default",
    *,
    load_skills: bool = True,
    load_mcp: bool = True,
) -> BaseAgent:
    """Create the full multi-agent system with an orchestrator and specialists.

    Returns an :class:`OrchestratorAgent` ready to handle requests.
    """
    orch = OrchestratorAgent()
    orch.memory.session_id = session_id
    orch.memory.entity_name = entity_name
    orch.memory.channel = channel

    # -- 子 agent ------------------------------------------------------------
    coder = CoderAgent()
    medical = MedicalAgent()
    companion = CompanionAgent()
    practical = PracticalAgent()

    for agent in (coder, medical, companion, practical):
        agent.memory = orch.memory  # 所有 agent 共享内存

    _load_persona(companion)

    if load_skills:
        _load_skills(coder, medical, companion, practical)

    # 初始化 LLM 并绑定工具
    for agent in (coder, medical, companion, practical):
        agent._init_llm()
        agent.bind_tools_to_llm()

    orch.register_agent("coder", coder)
    orch.register_agent("medical", medical)
    orch.register_agent("companion", companion)
    orch.register_agent("practical", practical)

    orch._init_llm()

    if load_mcp:
        await _init_mcp(orch)

    logger.info("Multi-agent system ready: orchestrator + %d specialists", len(orch.sub_agents))
    return orch


def _load_persona(agent: BaseAgent) -> None:
    """Load the core system personality from the shipped haven.md."""
    if not _SYSTEM_PERSONA.is_file():
        logger.warning("System persona not found: %s", _SYSTEM_PERSONA)
        return
    skill = SkillLoader.load_single(_SYSTEM_PERSONA)
    if skill is None:
        logger.warning("Failed to parse system persona: %s", _SYSTEM_PERSONA)
        return
    agent.skills[skill.name] = skill
    logger.debug("System persona loaded for '%s': %s", agent.name, skill.name)


def _load_skills(*agents: BaseAgent) -> None:
    skill_dir = find_user_path(settings.skill_directory)
    if not skill_dir.is_dir():
        return
    loaded = SkillLoader.load_from_dir(skill_dir)
    if not loaded:
        return
    for agent in agents:
        for skill in loaded:
            agent.skills[skill.name] = skill
    logger.debug("Skills loaded for %d agent(s): %d skill(s)", len(agents), len(loaded))


async def _init_mcp(orch: OrchestratorAgent) -> None:
    if not settings.mcp_enabled:
        return

    try:
        from haven.mcp import MCPManager, MCPServerConfig
    except ImportError as exc:
        logger.warning("MCP SDK not available, skipping (%s)", exc)
        return

    raw_configs = get_mcp_config()
    if not raw_configs:
        return

    configs: list[Any] = []
    for raw in raw_configs:
        try:
            configs.append(MCPServerConfig(**raw))
        except Exception as exc:
            logger.warning("Invalid MCP config, skipping: %s", exc)
            continue

    configs = [c for c in configs if c.enabled]
    if not configs:
        return

    orch.mcp_manager = MCPManager(configs)
    try:
        mcp_tools = await orch.mcp_manager.start()
    except Exception as exc:
        logger.warning("MCP connection failed: %s", exc)
        orch.mcp_manager = None
        return

    if mcp_tools:
        # 将 MCP 工具共享给所有子 agent
        for agent in orch.sub_agents.values():
            agent.register_mcp_tools(mcp_tools)
            agent.bind_tools_to_llm()
        logger.info("MCP: %d tool(s) shared with %d agent(s)", len(mcp_tools), len(orch.sub_agents))
