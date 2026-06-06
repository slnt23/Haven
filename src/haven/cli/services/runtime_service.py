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
    """CLI ↔ Runtime 桥梁。内部持有 Coordinator + ContextBuilder。"""

    def __init__(self):
        self._coordinator: Any = None
        self._runtime: Any = None  # general agent (兼容旧接口)
        self._initialized = False
        self._model: str | None = None
        self._session_id: str = "cli_main"
        self._entity_name: str = "cli_user"
        self._channel: str = "cli"

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

        try:
            from haven.runtime.factory import create_coordinator

            self._coordinator = await create_coordinator(
                session_id=session_id,
                entity_name=entity_name,
                channel=self._channel,
                load_mcp=load_mcp,
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
    # 核心 API
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
        plan = None

        try:
            if no_plan or self._is_simple(task):
                result = await self._runtime.run(task)
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
                if plan_obj.steps:
                    result = await self._coordinator._execute_steps(plan_obj, task)
                else:
                    agent = self._coordinator.agents.get(
                        plan_obj.agent_type, self._runtime
                    )
                    result = await agent.run(task)

        except Exception as exc:
            logger.error("run_task error: %s", exc)
            result = f"[错误] {exc}"

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

        from haven.runtime.registry import WorkflowRegistry

        wf_names = WorkflowRegistry.list_all()
        if workflow_name not in wf_names:
            return {
                "result": f"[错误] 工作流不存在: {workflow_name}。可用: {', '.join(wf_names)}",
                "workflow": workflow_name, "nodes_executed": 0, "elapsed_ms": 0,
            }

        t0 = time.monotonic()

        try:
            graph = WorkflowRegistry.build(workflow_name)
        except Exception as exc:
            return {
                "result": f"[错误] 构建工作流失败: {exc}",
                "workflow": workflow_name, "nodes_executed": 0, "elapsed_ms": 0,
            }

        state = self._make_workflow_state(workflow_name, task)
        logger.info("Workflow '%s': task=%s", workflow_name, task[:60])

        try:
            config = {
                "configurable": {
                    "thread_id": self._session_id,
                    "agent": self._runtime,
                }
            }
            result = await graph.ainvoke(state, config=config)
        except Exception as exc:
            logger.error("Workflow '%s' error: %s", workflow_name, exc)
            return {
                "result": f"[错误] {exc}",
                "workflow": workflow_name,
                "nodes_executed": len(state.get("node_outputs", {})),
                "elapsed_ms": int((time.monotonic() - t0) * 1000),
            }

        elapsed_ms = int((time.monotonic() - t0) * 1000)
        if result.get("status") == "failed":
            return {
                "result": "[工作流失败]\n" + "\n".join(result.get("errors", [])),
                "workflow": workflow_name,
                "nodes_executed": len(result.get("node_outputs", {})),
                "elapsed_ms": elapsed_ms,
            }

        return {
            "result": result.get("final_output") or "(完成)",
            "workflow": workflow_name,
            "nodes_executed": len(result.get("node_outputs", {})),
            "elapsed_ms": elapsed_ms,
        }

    @staticmethod
    def _make_workflow_state(wf_name: str, task: str) -> dict:
        base: dict = {
            "task": task, "session_id": "default", "messages": [],
            "errors": [], "completed_steps": [], "current_step": "",
            "node_outputs": {}, "node_retry_counts": {},
            "max_retries_per_node": 3, "status": "pending",
            "final_output": "", "started_at": 0.0,
        }
        if "dev" in wf_name:
            base.update({
                "architecture_doc": "", "source_code": "", "code_language": "python",
                "review_feedback": "", "review_score": 0.0, "review_blockers": [],
                "test_report": "", "test_passed": False, "test_failures": [],
            })
        elif "research" in wf_name:
            base.update({
                "research_topic": "", "raw_findings": [], "analyzed_insights": "",
                "final_report": "", "sources": [],
            })
        elif "diagnosis" in wf_name:
            base.update({
                "symptoms": "", "collected_info": "", "possible_causes": "",
                "diagnosis": "", "recommendations": "",
            })
        return base

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

    @staticmethod
    def _is_simple(task: str) -> bool:
        return len(task.strip()) < 20 and "?" not in task
