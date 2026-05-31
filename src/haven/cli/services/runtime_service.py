"""RuntimeService — CLI 与 Runtime 之间的唯一桥梁。

CLI 层禁止直接调用 ``haven.runtime`` 内部实现。
所有交互通过此 Service 完成。

用法::

    svc = RuntimeService()
    await svc.start(model="deepseek-v4-pro")

    # REPL 单轮
    reply = await svc.chat("帮我写代码")

    # 单轮执行（带规划）
    reply = await svc.run_task("写排序算法")

    # 流式
    async for token in svc.chat_stream("你好"):
        print(token, end="")

    await svc.stop()
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, AsyncIterator

from haven.cli.services.cli_service import CLIContext
from haven.cli.ui.console import render_warning

logger = logging.getLogger("haven.cli.service")


class RuntimeService:
    """CLI ↔ Runtime 桥梁。

    内部持有 PlannerAgent + AgentRuntime。
    对外暴露 chat / run_task / chat_stream 三个核心方法。
    """

    def __init__(self):
        self._planner: Any = None
        self._runtime: Any = None
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
        """初始化 Runtime：创建 PlannerAgent，加载 Skills/Tools/Memory。

        Returns:
            状态 dict: {model, skills, tools, workflows, memory_turns, providers}
        """
        if self._initialized:
            return self._status()

        self._model = model
        self._session_id = session_id
        self._entity_name = entity_name

        try:
            from haven.runtime.factory import create_agent

            self._planner = await create_agent(
                session_id=session_id,
                entity_name=entity_name,
                channel=self._channel,
                load_mcp=load_mcp,
            )
            self._runtime = self._planner.runtime

            # 模型切换
            if model:
                try:
                    self._runtime.switch_model(model)
                except Exception:
                    render_warning(f"模型 '{model}' 不可用，使用默认模型。")
                    self._model = None

            self._initialized = True
            logger.info("RuntimeService started: model=%s session=%s",
                         self._model or "default", session_id)

            return self._status()

        except Exception as exc:
            logger.error("Failed to start RuntimeService: %s", exc)
            raise RuntimeError(f"启动 Runtime 失败: {exc}") from exc

    async def stop(self) -> None:
        """清理资源：保存记忆、关闭 MCP 连接。"""
        if self._runtime is not None:
            try:
                await self._runtime.extract_facts_async()
            except Exception:
                pass

        self._planner = None
        self._runtime = None
        self._initialized = False

    # ==================================================================
    # 状态查询
    # ==================================================================

    def _status(self) -> dict[str, Any]:
        """构建当前状态快照。"""
        status: dict[str, Any] = {
            "model": self._model or "default",
            "skills": 0,
            "tools": 0,
            "workflows": 0,
            "providers": 0,
            "memory_turns": 0,
            "initialized": self._initialized,
        }

        if not self._runtime:
            return status

        try:
            from haven.skills.registry import SkillRegistry
            skills = SkillRegistry.list_all()
            status["skills"] = len(skills)
        except Exception:
            pass

        try:
            from haven.workflows.registry import WorkflowRegistry
            wf = WorkflowRegistry.list_all()
            status["workflows"] = len(wf)
        except Exception:
            pass

        try:
            tm = getattr(self._runtime, "_tool_manager", None)
            if tm:
                status["tools"] = len(tm.list_all())
                status["providers"] = len(tm.list_providers())
            else:
                tools = getattr(self._runtime, "_tools", {})
                status["tools"] = len(tools)
        except Exception:
            pass

        try:
            mm = getattr(self._runtime.memory, "manager", None)
            if mm:
                status["memory_turns"] = mm.turn_count
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
        """获取底层 AgentRuntime（仅供内部 Service 使用）。"""
        if not self._initialized:
            raise RuntimeError("RuntimeService 未初始化，请先调用 start()")
        return self._runtime

    def get_planner(self) -> Any:
        """获取 PlannerAgent（仅供内部 Service 使用）。"""
        if not self._initialized:
            raise RuntimeError("RuntimeService 未初始化，请先调用 start()")
        return self._planner

    # ==================================================================
    # 核心 API — CLI 通过这三个方法与 Runtime 交互
    # ==================================================================

    async def chat(self, task: str) -> str:
        """REPL 单轮对话。

        Planner 分析 → Runtime 执行 → 返回文本响应。
        简单对话跳过 Planner 直接 Runtime.run()。
        """
        if not self._initialized:
            return "[错误] Runtime 未初始化，请先调用 start()"

        try:
            return await self._planner.execute(task)
        except Exception as exc:
            logger.error("chat error: %s", exc)
            return f"[错误] {exc}"

    async def run_task(
        self,
        task: str,
        *,
        no_plan: bool = False,
        no_memory: bool = False,
    ) -> dict[str, Any]:
        """单轮任务执行。

        Returns:
            {result: str, plan: dict | None, elapsed_ms: int}
        """
        if not self._initialized:
            return {"result": "[错误] Runtime 未初始化", "plan": None, "elapsed_ms": 0}

        t0 = time.monotonic()
        plan = None

        try:
            if no_plan or self._is_simple(task):
                result = await self._runtime.run(task, use_memory=not no_memory)
            else:
                plan_obj = await self._planner.plan(task)
                plan = {
                    "goal": plan_obj.goal,
                    "intent": plan_obj.intent,
                    "complexity": plan_obj.complexity,
                    "skills": plan_obj.skills,
                    "workflow": plan_obj.workflow,
                    "steps": [s.model_dump() for s in plan_obj.steps],
                    "reasoning": plan_obj.reasoning,
                }

                if plan_obj.steps:
                    result = await self._planner._execute_steps(plan_obj, task)
                else:
                    result = await self._runtime.run(task, use_memory=not no_memory)

        except Exception as exc:
            logger.error("run_task error: %s", exc)
            result = f"[错误] {exc}"

        elapsed_ms = int((time.monotonic() - t0) * 1000)

        # 后台提取事实
        if self._runtime:
            asyncio.create_task(self._runtime.extract_facts_async())

        return {"result": result, "plan": plan, "elapsed_ms": elapsed_ms}

    async def run_workflow(
        self,
        workflow_name: str,
        task: str,
        *,
        checkpoint: bool = False,
    ) -> dict[str, Any]:
        """执行指定工作流。

        Returns:
            {result: str, workflow: str, nodes_executed: int, elapsed_ms: int}
        """
        if not self._initialized:
            return {"result": "[错误] Runtime 未初始化", "workflow": workflow_name,
                    "nodes_executed": 0, "elapsed_ms": 0}

        from haven.workflows.registry import WorkflowRegistry

        wf_names = WorkflowRegistry.list_all()
        if workflow_name not in wf_names:
            return {"result": f"[错误] 工作流不存在: {workflow_name}。可用: {', '.join(wf_names)}",
                    "workflow": workflow_name, "nodes_executed": 0, "elapsed_ms": 0}

        t0 = time.monotonic()

        try:
            graph = WorkflowRegistry.build(workflow_name)
        except Exception as exc:
            return {"result": f"[错误] 构建工作流失败: {exc}",
                    "workflow": workflow_name, "nodes_executed": 0, "elapsed_ms": 0}

        # 按名称选择 State 类型
        state = self._make_workflow_state(workflow_name, task)
        state._runtime = self._runtime
        state.session_id = self._session_id

        if not checkpoint:
            graph._checkpointer = None

        logger.info("Workflow '%s': %d nodes, task=%s",
                     workflow_name, len(graph._nodes), task[:60])

        try:
            result_state = await graph.run(state, runtime=self._runtime)
        except Exception as exc:
            logger.error("Workflow '%s' error: %s", workflow_name, exc)
            return {"result": f"[错误] {exc}", "workflow": workflow_name,
                    "nodes_executed": len(state.node_outputs), "elapsed_ms": int((time.monotonic() - t0) * 1000)}

        elapsed_ms = int((time.monotonic() - t0) * 1000)

        if result_state.status == "failed":
            return {"result": "[工作流失败]\n" + "\n".join(result_state.errors),
                    "workflow": workflow_name,
                    "nodes_executed": len(result_state.node_outputs),
                    "elapsed_ms": elapsed_ms}

        return {"result": result_state.final_output or "(完成)",
                "workflow": workflow_name,
                "nodes_executed": len(result_state.node_outputs),
                "elapsed_ms": elapsed_ms}

    @staticmethod
    def _make_workflow_state(wf_name: str, task: str) -> Any:
        from haven.workflows.state import (
            WorkflowState, DevWorkflowState, ResearchWorkflowState, DiagnosisWorkflowState,
        )
        if "dev" in wf_name:
            return DevWorkflowState(task=task)
        elif "research" in wf_name:
            return ResearchWorkflowState(task=task)
        elif "diagnosis" in wf_name:
            return DiagnosisWorkflowState(task=task)
        return WorkflowState(task=task)

    async def chat_stream(self, task: str) -> AsyncIterator[str]:
        """REPL 流式对话（逐 token 返回）。

        Usage:
            async for token in svc.chat_stream("你好"):
                ui.write(token)
        """
        if not self._initialized:
            yield "[错误] Runtime 未初始化"
            return

        # 当前 Runtime 不支持原生 streaming，模拟逐句输出
        try:
            result = await self._planner.execute(task)
            # 按字符分块模拟流式
            chunk_size = 3
            for i in range(0, len(result), chunk_size):
                yield result[i : i + chunk_size]
                await asyncio.sleep(0.01)
        except Exception as exc:
            logger.error("chat_stream error: %s", exc)
            yield f"[错误] {exc}"

    def switch_model(self, model_name: str) -> str:
        """切换模型。返回实际设置的模型名。"""
        if not self._initialized:
            raise RuntimeError("Runtime 未初始化")
        try:
            actual = self._runtime.switch_model(model_name)
            self._model = model_name
            return actual
        except Exception as exc:
            raise RuntimeError(f"模型切换失败: {exc}") from exc

    # ==================================================================
    # 内部
    # ==================================================================

    @staticmethod
    def _is_simple(task: str) -> bool:
        """启发式判断是否为简单对话（跳过 Planner，节省一次 LLM 调用）。"""
        cleaned = task.strip().lower().rstrip("?!.。！？")
        simple = {
            "你好", "hi", "hello", "谢谢", "thanks", "再见", "bye",
            "在吗", "你是谁", "你能做什么", "早上好", "晚安",
        }
        return cleaned in simple or len(cleaned) <= 2
