"""RuntimeService — CLI 与 Runtime 之间的唯一桥梁。

CLI 层禁止直接调用 ``haven.runtime`` 内部实现。
所有交互通过此 Service 完成。
"""

from __future__ import annotations

import logging
import time
from typing import Any, AsyncIterator

from haven.cli.ui.console import render_warning

logger = logging.getLogger("haven.cli.service")


class RuntimeService:
    """CLI ↔ Runtime 桥梁。内部持有 Coordinator。"""

    def __init__(self):
        self._coordinator: Any = None
        self._runtime: Any = None
        self._initialized = False
        self._model: str | None = None
        self._session_id: str = "cli_main"
        self._entity_name: str = "cli_user"
        self._channel: str = "cli"
        self._use_memory: bool = True

    # ==================================================================
    # 生命周期
    # ==================================================================

    async def start(
        self,
        *,
        model: str | None = None,
        session_id: str = "cli_main",
        entity_name: str = "cli_user",
        load_mcp: bool = False,
        use_memory: bool = True,
    ) -> dict[str, Any]:
        if self._initialized:
            return self._status()

        self._model = model
        self._session_id = session_id
        self._entity_name = entity_name
        self._use_memory = use_memory

        try:
            from haven.runtime.factory import create_coordinator

            self._coordinator = await create_coordinator(
                session_id=session_id,
                entity_name=entity_name,
                channel=self._channel,
                load_mcp=load_mcp,
                use_memory=use_memory,
            )
            self._runtime = self._coordinator.runtime

            if model:
                try:
                    self._coordinator.switch_model(model)
                except Exception:
                    render_warning(f"模型 '{model}' 不可用，使用默认模型。")
                    self._model = None

            self._initialized = True
            logger.info(
                "RuntimeService started: model=%s session=%s",
                self._model or "default", session_id,
            )
            return self._status()

        except Exception as exc:
            logger.error("Failed to start RuntimeService: %s", exc)
            raise RuntimeError(f"启动 Runtime 失败: {exc}") from exc

    async def stop(self) -> None:
        self._coordinator = None
        self._runtime = None
        self._initialized = False

    # ==================================================================
    # 状态查询
    # ==================================================================

    def _status(self) -> dict[str, Any]:
        status: dict[str, Any] = {
            "model": self._model or "default",
            "skills": 0, "tools": 0, "workflows": 0,
            "providers": 0, "memory_turns": 0,
            "initialized": self._initialized,
        }

        if not self._coordinator:
            return status

        try:
            from haven.skills.registry import SkillRegistry
            status["skills"] = len(SkillRegistry.list_all())
        except Exception:
            pass

        try:
            from haven.runtime.registry import WorkflowRegistry
            status["workflows"] = len(WorkflowRegistry.list_all())
        except Exception:
            pass

        try:
            agents = self._coordinator.agents
            agent_names = list(agents.keys())
            tools = set()
            for a in agents.values():
                for t in getattr(a, "_tools", []):
                    tools.add(t.name)
            status["tools"] = len(tools)
            status["providers"] = len(agent_names)
        except Exception:
            pass

        try:
            if self._runtime:
                status["memory_turns"] = self._runtime.state.turn_count
        except Exception:
            pass

        return status

    @property
    def is_initialized(self) -> bool:
        return self._initialized

    @property
    def model(self) -> str | None:
        return self._model

    def get_runtime(self) -> Any:
        if not self._initialized:
            raise RuntimeError("RuntimeService 未初始化，请先调用 start()")
        return self._runtime

    def get_planner(self) -> Any:
        if not self._initialized:
            raise RuntimeError("RuntimeService 未初始化，请先调用 start()")
        return self._coordinator

    # ==================================================================
    # 核心 API — 委托给 Coordinator
    # ==================================================================

    async def chat(self, task: str) -> str:
        if not self._initialized:
            return "[错误] Runtime 未初始化，请先调用 start()"
        try:
            return await self._coordinator.execute(task)
        except Exception as exc:
            logger.error("chat error: %s", exc)
            return f"[错误] {exc}"

    async def run_task(
        self, task: str, *, no_plan: bool = False, no_memory: bool = False,
    ) -> dict[str, Any]:
        if not self._initialized:
            return {"result": "[错误] Runtime 未初始化", "plan": None, "elapsed_ms": 0}

        t0 = time.monotonic()

        try:
            if no_plan:
                result = await self._runtime.run(task)
                plan = None
            else:
                plan_obj = await self._coordinator.plan(task)
                plan = {
                    "goal": plan_obj.goal, "intent": plan_obj.intent,
                    "agent_type": plan_obj.agent_type,
                    "complexity": plan_obj.complexity,
                    "skills": plan_obj.skills, "workflow": plan_obj.workflow,
                    "steps": [s.model_dump() for s in plan_obj.steps],
                    "reasoning": plan_obj.reasoning,
                }
                result = await self._coordinator.execute(task)
        except Exception as exc:
            logger.error("run_task error: %s", exc)
            result = f"[错误] {exc}"
            plan = None

        elapsed_ms = int((time.monotonic() - t0) * 1000)
        return {"result": result, "plan": plan, "elapsed_ms": elapsed_ms}

    async def run_workflow(
        self, workflow_name: str, task: str, *, checkpoint: bool = False,
    ) -> dict[str, Any]:
        if not self._initialized:
            return {
                "result": "[错误] Runtime 未初始化",
                "workflow": workflow_name, "nodes_executed": 0, "elapsed_ms": 0,
            }

        t0 = time.monotonic()

        from haven.runtime.registry import WorkflowRegistry

        wf_names = WorkflowRegistry.list_all()
        if workflow_name not in wf_names:
            return {
                "result": f"[错误] 工作流不存在: {workflow_name}。可用: {', '.join(wf_names)}",
                "workflow": workflow_name, "nodes_executed": 0, "elapsed_ms": 0,
            }

        # 通过 plan 触发 workflow 路径
        from haven.runtime.coordinator import ExecutionPlan

        plan = ExecutionPlan(
            goal=task, intent="task", agent_type="general",
            complexity="complex", skills=[], workflow=workflow_name,
            steps=[], reasoning="手动触发工作流",
        )

        try:
            result = await self._coordinator._execute_via_workflow(plan, task)
        except Exception as exc:
            logger.error("Workflow '%s' error: %s", workflow_name, exc)
            return {
                "result": f"[错误] {exc}",
                "workflow": workflow_name, "nodes_executed": 0,
                "elapsed_ms": int((time.monotonic() - t0) * 1000),
            }

        elapsed_ms = int((time.monotonic() - t0) * 1000)
        return {
            "result": result,
            "workflow": workflow_name,
            "nodes_executed": 0,
            "elapsed_ms": elapsed_ms,
        }

    async def chat_stream(self, task: str) -> AsyncIterator[str]:
        if not self._initialized:
            yield "[错误] Runtime 未初始化"
            return
        try:
            async for chunk in self._coordinator.execute_stream(task):
                yield chunk
        except Exception as exc:
            logger.error("chat_stream error: %s", exc)
            yield f"[错误] {exc}"

    def switch_model(self, model_name: str) -> str:
        if not self._initialized:
            raise RuntimeError("Runtime 未初始化")
        try:
            actual = self._coordinator.switch_model(model_name)
            self._model = actual
            return actual
        except Exception:
            return self._model or "unknown"

    # ==================================================================
    # 斜杠命令桥接 — CLI 通过这里查询，不直调内部
    # ==================================================================

    def list_skills(self) -> str:
        from haven.skills.registry import SkillRegistry

        all_s = SkillRegistry.list_all()
        if not all_s:
            return "(未加载 skill)"

        lines = [f"已加载 {len(all_s)} 个 skill:"]
        for name, s in sorted(all_s.items()):
            dtype = "人格" if s.default else "领域"
            lines.append(f"  [{dtype}] {name} — {s.description or '(无描述)'}")
        return "\n".join(lines)

    def list_tools(self) -> str:
        if not self._initialized:
            return "(Runtime 未初始化)"

        tools: list[Any] = []
        for agent in self._coordinator.agents.values():
            for t in getattr(agent, "_tools", []):
                if t not in tools:
                    tools.append(t)

        if not tools:
            return "(未加载工具)"

        lines = [f"已加载 {len(tools)} 个工具:"]
        for t in sorted(tools, key=lambda x: x.name):
            desc = getattr(t, "description", "") or ""
            lines.append(f"  {t.name} — {desc}" if desc else f"  {t.name}")
        return "\n".join(lines)

    def get_memory_stats(self) -> str:
        if not self._initialized or not self._runtime:
            return "(Runtime 未初始化)"

        st = self._runtime.state
        lines = [
            f"会话: {st.session_id}",
            f"实体: {st.entity_name}",
            f"轮次: {st.turn_count}",
            f"频道: {st.channel}",
            f"长期记忆: {'开启' if self._use_memory else '关闭'}",
        ]
        if self._coordinator and getattr(self._coordinator, "_fact_store", None):
            facts = self._coordinator._fact_store.get_all(st.entity_name)
            lines.append(f"事实条数: {len(facts)}")
        if st.active_skills:
            lines.append(f"当前 skills: {', '.join(st.active_skills)}")
        if st.active_tools:
            lines.append(f"当前 tools: {', '.join(st.active_tools)}")
        return "\n".join(lines)

    @staticmethod
    def list_workflows() -> str:
        from haven.runtime.registry import WorkflowRegistry

        ctx = WorkflowRegistry.get_selection_context()
        if "(无可用" in ctx:
            return "(未注册工作流)"
        return ctx

    @staticmethod
    def list_models() -> str:
        from haven.config import load_models_config

        models = load_models_config()
        lines = ["可用模型:"]
        for name in sorted(models.keys()):
            lines.append(f"  {name}")
        return "\n".join(lines)

    def current_model(self) -> str:
        if self._runtime and self._runtime.llm:
            return getattr(self._runtime.llm, "model_name", "unknown")
        return "(Runtime 未初始化)"

    async def reset_session(self) -> None:
        """清空对话历史（checkpointer 线程 + turn 状态）。"""
        if self._coordinator:
            await self._coordinator.reset_session()

    def reset(self) -> None:
        if self._coordinator:
            self._coordinator.reset()
