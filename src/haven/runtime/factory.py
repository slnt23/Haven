"""Runtime 工厂 —— 装配完整的 Haven 运行时系统。

创建流程：
  Config → LLM → CapabilityLoader → SessionManager → Executor → Runtime

Runtime 通过 Executor 执行任务，不直接接触 Agent。
"""

from __future__ import annotations

import aiosqlite
import asyncio
import logging
import uuid
from pathlib import Path
from typing import Any

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from haven.config import load_config
from haven.model.llm import ModelFactory
from haven.session.manager import SessionManager
from haven.agent.base import Agent
from haven.runtime.context import ContextBuilder
from haven.infrastructure.types import StreamChunk
from haven.capability.registry import CapabilityRegistry
from haven.capability.loader import CapabilityLoader
from haven.execution.planner import Planner
from haven.execution.pipeline import ExecutionPipeline
from haven.execution.executor import Executor
from haven.execution.request import ExecutionRequest

logger = logging.getLogger("haven.factory")


class Runtime:
    """Haven 运行时容器。

    持有 Executor（唯一执行入口）。
    Runtime 不直接接触 Agent、Planner、或 Pipeline。
    """

    __slots__ = (
        "executor", "llm", "registry", "checkpointer",
        "session_manager", "agents", "_sqlite_conn", "_memory",
        "_model_factory", "_last_memory_task", "_current_session_id",
    )

    def __init__(
        self,
        executor: Executor,
        llm: Any,
        registry: CapabilityRegistry,
        checkpointer: Any,
        session_manager: SessionManager,
        agents: dict[str, Agent],
        sqlite_conn: Any = None,
        memory_manager: Any = None,
        model_factory: Any = None,
    ) -> None:
        self.executor = executor
        self.llm = llm
        self.registry = registry
        self.checkpointer = checkpointer
        self.session_manager = session_manager
        self.agents = agents
        self._sqlite_conn = sqlite_conn
        self._memory = memory_manager
        self._model_factory = model_factory
        self._last_memory_task = None
        self._current_session_id = ""

    async def execute(self, task: str, session_id: str = "") -> str:
        """规划 + 执行：通过 Executor。"""
        sid = session_id or self._current_session_id
        request = ExecutionRequest(task=task, session_id=sid)
        response = await self.executor.execute(request)
        self._trigger_memory(task, response.result)
        return response.result

    async def execute_stream(self, task: str, session_id: str = ""):
        """规划 + 流式执行：通过 Executor。"""
        sid = session_id or self._current_session_id
        request = ExecutionRequest(task=task, session_id=sid)
        text_chunks: list[str] = []
        async for chunk in self.executor.execute_stream(request):
            if chunk.kind == "text":
                text_chunks.append(chunk.content)
            yield chunk
        self._trigger_memory(task, "".join(text_chunks))

    def _trigger_memory(self, user_input: str, agent_response: str) -> None:
        if self._memory is None:
            return
        self._last_memory_task = asyncio.create_task(
            self._memory.after_turn(user_input, agent_response)
        )

    async def flush_memory(self) -> None:
        """等待最后一个 Memory 写入任务完成。退出前调用。"""
        if self._last_memory_task is not None and not self._last_memory_task.done():
            try:
                await asyncio.wait_for(self._last_memory_task, timeout=5.0)
            except asyncio.TimeoutError:
                pass
            except Exception:
                pass

    async def reset_session(self, session_id: str = "") -> None:
        """切换到全新 Session（新 UUID），彻底隔离旧对话历史。

        不依赖 adelete_thread 成功——旧 thread 自然不再被引用。
        长期记忆（SQLite + VectorStore）不受影响。
        """
        old_sid = session_id or self._current_session_id

        # 1. 保留 user_id / channel，生成新 session_id
        old = self.session_manager.get(old_sid) if old_sid else None
        user_id = old.user_id if old else "user"
        channel = old.channel if old else "cli"
        new_sid = str(uuid.uuid4())

        # 2. 关闭旧 Session（不再引用旧 thread_id）
        if old_sid:
            self.session_manager.close(old_sid)

        # 3. 尝试清理旧 thread（尽力而为，失败不影响新 Session 隔离）
        try:
            if old_sid:
                await self.checkpointer.adelete_thread(old_sid)
        except Exception:
            logger.info("旧 checkpointer thread 清理失败（不影响隔离）: %s", old_sid)

        # 4. 创建新 Session + 更新当前 session_id
        self.session_manager.create(new_sid, user_id=user_id, channel=channel)
        self._current_session_id = new_sid

        # 5. 重置 Agent
        for agent in self.agents.values():
            agent.reset()

        logger.info("Session 已切换: %s → %s", old_sid, new_sid)

    def reset(self) -> None:
        for agent in self.agents.values():
            agent.reset()

    def switch_model(self, model_name: str) -> str:
        for agent in self.agents.values():
            if hasattr(agent, "llm") and self._model_factory is not None:
                agent.llm = self._model_factory.create(model_name)._raw
                agent._agent = None
        self.llm = self.agents.get("general").llm if self.agents.get("general") else self.llm
        return model_name

    async def close(self) -> None:
        if self.registry:
            try:
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
    session_id: str = "",
    entity_name: str = "user",
    channel: str = "default",
    *,
    load_skills: bool = True,
    load_mcp: bool = True,
    use_memory: bool | None = None,
) -> Runtime:
    """创建完整的 Haven 运行时系统。"""
    # 1. CapabilityRegistry
    registry = CapabilityRegistry()

    # 2. ModelFactory + LLM
    cfg = load_config()
    model_factory = ModelFactory(cfg)
    llm = model_factory.create()._raw

    # 3. CapabilityLoader
    cap_loader = CapabilityLoader(registry)
    await cap_loader.load_all(
        skill_dir=cfg.skill_directory,
        load_mcp=load_mcp,
        mcp_enabled=cfg.mcp_enabled,
    )
    all_tools = registry.list_langchain_tools()

    # 4. Checkpointer + SessionManager
    db_dir = Path.cwd() / "resource"
    db_dir.mkdir(parents=True, exist_ok=True)
    conn = await aiosqlite.connect(str(db_dir / "checkpoint.db"))
    checkpointer = AsyncSqliteSaver(conn)
    await checkpointer.setup()

    session_manager = SessionManager(checkpointer=checkpointer)
    session_id = session_id or str(uuid.uuid4())
    session_manager.create(session_id, user_id=entity_name, channel=channel)

    # 5. MemoryManager + ContextBuilder
    memory_on = cfg.memory.enabled if use_memory is None else use_memory
    memory_manager = None
    if memory_on:
        from haven.memory.fact_store import FactStore
        from haven.memory.manager import MemoryManager
        from haven.memory.extractor import FactExtractor

        memory_path = Path.cwd() / cfg.memory.db_path
        fact_store = FactStore(memory_path)

        aux_llm = model_factory.create(cfg.auxiliary_model)._raw
        extractor = FactExtractor(aux_llm)

        # VectorStore 可选：依赖缺失时自动降级
        vector_store = None
        try:
            from haven.memory.vector_store import MemoryVectorStore
            vector_store = MemoryVectorStore()
        except Exception:
            logger.debug("MemoryVectorStore 不可用，仅 SQLite 检索")

        memory_manager = MemoryManager(
            fact_store,
            extractor=extractor,
            vector_store=vector_store,
            entity_name=entity_name,
        )

    context_builder = ContextBuilder()

    # 6. Agents — 使用 Agent 层
    agent_defs = _load_agent_definitions()
    agents: dict[str, Agent] = {}
    for name, ad in agent_defs.items():
        agents[name] = Agent(
            name=name, llm=llm, tools=list(all_tools),
            checkpointer=checkpointer, agent_prompt=ad.get("prompt", ""),
        )

    # 7. WorkflowRegistry + WorkflowEngine
    from haven.workflow.definitions import dev, diagnosis, research, triage  # noqa: F401
    from haven.workflow.registry import WorkflowRegistry
    from haven.workflow.engine import WorkflowEngine

    # 8. Execution Layer (Planner → Pipeline → Executor)
    planner = Planner(
        llm=llm,
        workflow_registry=WorkflowRegistry,
        capability_registry=registry,
    )

    pipeline = ExecutionPipeline(
        agents=agents,
        workflow_registry=WorkflowRegistry,
        session_manager=session_manager,
        context_builder=context_builder,
        capability_registry=registry,
        memory_manager=memory_manager,
    )

    executor = Executor(
        planner=planner,
        pipeline=pipeline,
        session_manager=session_manager,
    )

    # 9. 装配 Runtime
    runtime = Runtime(
        executor=executor,
        llm=llm,
        registry=registry,
        checkpointer=checkpointer,
        session_manager=session_manager,
        agents=agents,
        sqlite_conn=conn,
        memory_manager=memory_manager,
        model_factory=model_factory,
    )
    runtime._current_session_id = session_id

    logger.info(
        "Runtime ready: %d agents, %d skills, %d workflows, %d tools",
        len(agents), registry.skill_count,
        len(WorkflowRegistry.list_all()), registry.tool_count,
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
