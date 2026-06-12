"""Runtime 工厂 —— 装配完整的 Haven 运行时系统。

创建流程：
  Config → LLM → CapabilityLoader → Registry → ContextBuilder → BaseAgent → Coordinator → Dispatcher

返回 Runtime 命名空间，提供 execute() / execute_stream() 便捷方法。
"""

from __future__ import annotations

import aiosqlite
import asyncio
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
from haven.runtime.stream import StreamChunk
from haven.runtime.dispatcher import Dispatcher
from haven.capability.registry import CapabilityRegistry
from haven.capability.loader import CapabilityLoader, SkillLoader

logger = logging.getLogger("haven.factory")


class Runtime:
    """Haven 运行时容器。"""

    __slots__ = (
        "coordinator", "dispatcher", "llm", "registry",
        "checkpointer", "state", "agents", "_sqlite_conn", "_pipeline",
    )

    def __init__(
        self,
        coordinator: Coordinator,
        dispatcher: Dispatcher,
        llm: Any,
        registry: CapabilityRegistry,
        checkpointer: Any,
        state: RuntimeState,
        agents: dict[str, BaseAgent],
        sqlite_conn: Any = None,
        pipeline: Any = None,
    ) -> None:
        self.coordinator = coordinator
        self.dispatcher = dispatcher
        self.llm = llm
        self.registry = registry
        self.checkpointer = checkpointer
        self.state = state
        self.agents = agents
        self._sqlite_conn = sqlite_conn
        self._pipeline = pipeline

    async def execute(self, task: str) -> str:
        plan = await self.coordinator.plan(task)
        result = await self.dispatcher.dispatch(plan, task)
        self._trigger_memory(task, result)
        return result

    async def execute_stream(self, task: str):
        plan = await self.coordinator.plan(task)
        yield StreamChunk(
            kind="plan",
            content=f"{plan.intent} → {plan.agent_type} (复杂度: {plan.complexity})",
        )
        text_chunks: list[str] = []
        async for chunk in self.dispatcher.dispatch_stream(plan, task):
            if chunk.kind == "text":
                text_chunks.append(chunk.content)
            yield chunk
        self._trigger_memory(task, "".join(text_chunks))

    def _trigger_memory(self, user_input: str, agent_response: str) -> None:
        if self._pipeline is None:
            return
        asyncio.create_task(self._pipeline.after_turn(user_input, agent_response))

    async def reset_session(self) -> None:
        self.state.reset_turn()
        for agent in self.agents.values():
            agent.reset()
        if self.checkpointer is not None:
            try:
                await self.checkpointer.adelete_thread(self.state.session_id)
            except Exception as exc:
                logger.warning("清空 checkpointer 线程失败，尝试覆盖: %s", exc)
                try:
                    for agent in self.agents.values():
                        if agent._agent is not None:
                            config = agent._build_config()
                            await agent._agent.aupdate_state(config, {"messages": []})
                except Exception:
                    pass

    def reset(self) -> None:
        self.state.reset_turn()
        for agent in self.agents.values():
            agent.reset()

    def switch_model(self, model_name: str) -> str:
        for agent in self.agents.values():
            if hasattr(agent, "llm"):
                agent.llm = create_llm(model_name)
                agent._agent = None
        self.llm = self.agents.get("general").llm if self.agents.get("general") else self.llm
        return model_name

    async def close(self) -> None:
        if self.registry:
            try:
                from haven.capability.loader import CapabilityLoader
                loader = CapabilityLoader(self.registry)
                await loader.stop_all()
            except Exception as exc:
                logger.debug("CapabilityLoader close: %s", exc)
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
    """创建完整的 Haven 运行时系统。"""
    state = RuntimeState()
    state.session_id = session_id
    state.entity_name = entity_name
    state.channel = channel

    # 1. CapabilityRegistry —— 统一的能力注册中心
    registry = CapabilityRegistry()

    # 2. LLM
    llm = create_llm()

    # 3. CapabilityLoader —— 加载 Tools + Skills
    cap_loader = CapabilityLoader(registry)
    await cap_loader.load_all(
        skill_dir=settings.skill_directory,
        load_mcp=load_mcp,
        mcp_enabled=settings.mcp_enabled,
    )
    all_tools = registry.list_langchain_tools()

    # 4. Shared Checkpointer
    db_dir = Path.cwd() / "resource"
    db_dir.mkdir(parents=True, exist_ok=True)
    conn = await aiosqlite.connect(str(db_dir / "checkpoint.db"))
    checkpointer = AsyncSqliteSaver(conn)
    await checkpointer.setup()

    # 5. ContextBuilder + 长期记忆
    context_builder = ContextBuilder()

    memory_on = settings.memory_enabled if use_memory is None else use_memory
    fact_store = None
    pipeline = None
    if memory_on:
        from haven.memory.fact_store import FactStore

        memory_path = Path.cwd() / settings.memory_db_path
        fact_store = FactStore(memory_path)

        from haven.config import get_auxiliary_model
        from haven.memory.extractor import FactExtractor
        from haven.memory.pipeline import MemoryPipeline

        aux_llm = create_llm(get_auxiliary_model())
        pipeline = MemoryPipeline(
            FactExtractor(aux_llm),
            fact_store,
            entity_name=entity_name,
        )

    # 6. Create Agents —— 共享 registry 中的工具
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

    # 7. WorkflowRegistry
    from haven.runtime.workflows import dev, diagnosis, research  # noqa: F401
    from haven.runtime.registry import WorkflowRegistry

    # 8. Coordinator
    coordinator = Coordinator(
        llm=llm,
        workflow_registry=WorkflowRegistry,
        capability_registry=registry,
    )

    # 9. Dispatcher
    dispatcher = Dispatcher(
        agents=agents,
        workflow_registry=WorkflowRegistry,
        state=state,
        context_builder=context_builder,
        capability_registry=registry,
        fact_store=fact_store,
        use_memory=memory_on,
    )

    # 10. 装配 Runtime
    runtime = Runtime(
        coordinator=coordinator,
        dispatcher=dispatcher,
        llm=llm,
        registry=registry,
        checkpointer=checkpointer,
        state=state,
        agents=agents,
        sqlite_conn=conn,
        pipeline=pipeline,
    )

    logger.info(
        "Runtime ready: %d agents, %d skills, %d workflows, %d tools",
        len(agents),
        registry.skill_count,
        len(WorkflowRegistry.list_all()),
        registry.tool_count,
    )
    return runtime


def _load_agent_definitions() -> dict[str, Any]:
    from omegaconf import OmegaConf

    path = Path(__file__).resolve().parent.parent / "config" / "haven.yaml"
    config = OmegaConf.load(path)
    user_path = Path.cwd() / "haven.yaml"
    if user_path.is_file():
        config = OmegaConf.merge(config, OmegaConf.load(user_path))

    agents_cfg = config.get("agents", {})
    if hasattr(agents_cfg, "items"):
        return {k: dict(v) for k, v in agents_cfg.items()}
    return dict(agents_cfg)
