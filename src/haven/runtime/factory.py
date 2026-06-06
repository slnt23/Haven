"""Runtime 工厂 —— 装配完整的 Haven 运行时系统。

创建流程：
  Config → LLM → ToolLoader → Registry → ContextBuilder → BaseAgent → Coordinator → Dispatcher

返回一个 Runtime 命名空间，包含 coordinator 和 dispatcher，
以及便捷方法 execute() / execute_stream()。
"""

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
from haven.runtime.dispatcher import Dispatcher
from haven.skills.loader import SkillLoader
from haven.skills.registry import SkillRegistry

logger = logging.getLogger("haven.factory")


class Runtime:
    """Haven 运行时容器。

    持有 coordinator（规划）和 dispatcher（执行），
    提供 execute() / execute_stream() 便捷方法。
    """

    __slots__ = (
        "coordinator", "dispatcher", "llm", "tool_loader",
        "checkpointer", "state", "agents", "_sqlite_conn",
    )

    def __init__(
        self,
        coordinator: Coordinator,
        dispatcher: Dispatcher,
        llm: Any,
        tool_loader: Any,
        checkpointer: Any,
        state: RuntimeState,
        agents: dict[str, BaseAgent],
        sqlite_conn: Any = None,
    ) -> None:
        self.coordinator = coordinator
        self.dispatcher = dispatcher
        self.llm = llm
        self.tool_loader = tool_loader
        self.checkpointer = checkpointer
        self.state = state
        self.agents = agents
        self._sqlite_conn = sqlite_conn  # 原始 aiosqlite 连接，用于 close()

    async def execute(self, task: str) -> str:
        """规划 + 执行：一步完成。"""
        plan = await self.coordinator.plan(task)
        return await self.dispatcher.dispatch(plan, task)

    async def execute_stream(self, task: str):
        """规划 + 流式执行。"""
        plan = await self.coordinator.plan(task)
        async for chunk in self.dispatcher.dispatch_stream(plan, task):
            yield chunk

    async def reset_session(self) -> None:
        """清空当前会话。"""
        self.state.reset_turn()
        for agent in self.agents.values():
            agent.reset()
        if self.checkpointer is not None:
            try:
                await self.checkpointer.adelete_thread(self.state.session_id)
            except Exception as exc:
                logger.warning("清空 checkpointer 线程失败: %s", exc)

    def reset(self) -> None:
        """同步重置（仅 turn 状态）。"""
        self.state.reset_turn()
        for agent in self.agents.values():
            agent.reset()

    def switch_model(self, model_name: str) -> str:
        """运行时切换模型。"""
        for agent in self.agents.values():
            if hasattr(agent, "llm"):
                agent.llm = create_llm(model_name)
                agent._agent = None  # 触发 Agent 重建
        self.llm = self.agents.get("general").llm if self.agents.get("general") else self.llm
        return model_name

    async def close(self) -> None:
        """优雅关闭：停止 ToolLoader → 关闭 SQLite 连接。

        必须在事件循环关闭前调用，否则 aiosqlite 后台线程会报错。
        """
        # 1. 停止所有 Tool Provider（断开 MCP 连接等）
        if self.tool_loader:
            try:
                await self.tool_loader.stop_all()
            except Exception as exc:
                logger.debug("ToolLoader close: %s", exc)

        # 2. 关闭 SQLite 连接（必须在事件循环关闭前执行）
        if self._sqlite_conn:
            try:
                await self._sqlite_conn.close()
            except Exception as exc:
                logger.debug("SQLite close: %s", exc)


async def create_runtime(
    session_id: str = "default",
    entity_name: str = "user",
    channel: str = "default",
    *,
    load_skills: bool = True,
    load_mcp: bool = True,
    use_memory: bool | None = None,
) -> Runtime:
    """创建完整的 Haven 运行时系统。

    返回 Runtime 实例，其 execute(task) 为统一入口。
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

    # 3. ToolLoader → Registry → list[BaseTool]
    from haven.tools.loader import ToolLoader

    loader = ToolLoader()
    all_tools = await loader.load_all(load_mcp=load_mcp)

    # 4. Shared Checkpointer
    db_dir = Path.cwd() / "resource"
    db_dir.mkdir(parents=True, exist_ok=True)
    conn = await aiosqlite.connect(str(db_dir / "checkpoint.db"))
    checkpointer = AsyncSqliteSaver(conn)
    await checkpointer.setup()

    # 5. ContextBuilder + FactStore
    context_builder = ContextBuilder()

    memory_on = settings.memory_enabled if use_memory is None else use_memory
    fact_store = None
    if memory_on:
        from haven.memory.fact_store import FactStore

        memory_path = Path.cwd() / settings.memory_db_path
        fact_store = FactStore(memory_path)

    # 6. Create Agents — 所有 Agent 共享全部工具
    agent_defs = _load_agent_definitions()

    agents: dict[str, BaseAgent] = {}
    for name, ad in agent_defs.items():
        agents[name] = BaseAgent(
            name=name,
            llm=llm,
            tools=list(all_tools),
            checkpointer=checkpointer,
            state=state,
            agent_prompt=ad.get("prompt", ""),
        )

    # 7. 注册预定义工作流（side-effect import）
    from haven.runtime.workflows import dev, diagnosis, research  # noqa: F401
    from haven.runtime.registry import WorkflowRegistry

    # 8. Coordinator（仅规划）
    coordinator = Coordinator(
        llm=llm,
        workflow_registry=WorkflowRegistry,
    )

    # 9. Dispatcher（执行调度）
    dispatcher = Dispatcher(
        agents=agents,
        workflow_registry=WorkflowRegistry,
        state=state,
        context_builder=context_builder,
        fact_store=fact_store,
        use_memory=memory_on,
    )

    # 10. 装配 Runtime（传入 SQLite 连接用于优雅关闭）
    runtime = Runtime(
        coordinator=coordinator,
        dispatcher=dispatcher,
        llm=llm,
        tool_loader=loader,
        checkpointer=checkpointer,
        state=state,
        agents=agents,
        sqlite_conn=conn,
    )

    logger.info(
        "Runtime ready: %d agents, %d skills, %d workflows, %d tools",
        len(agents),
        len(SkillRegistry.list_all()),
        len(WorkflowRegistry.list_all()),
        len(all_tools),
    )
    return runtime


def _load_agent_definitions() -> dict[str, Any]:
    """从 haven.yaml 加载 Agent 定义（仅 description + prompt）。"""
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


# ==================================================================
# Skill 加载
# ==================================================================

_SYSTEM_PERSONA = Path(__file__).resolve().parent.parent / "config" / "haven.md"


def _load_all_skills() -> None:
    """加载系统人格 + 用户领域技能。"""
    if _SYSTEM_PERSONA.is_file():
        persona = SkillLoader.load_single(_SYSTEM_PERSONA)
        if persona is not None:
            SkillRegistry.register_instance(persona)

    user_dir = find_user_path(settings.skill_directory)
    if user_dir.is_dir():
        for skill in SkillLoader.load_from_dir(user_dir):
            SkillRegistry.register_instance(skill)
