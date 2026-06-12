"""ExecutionPipeline —— 执行管道，处理 Plan → Agent 的调度。

三条执行路径：
  1. 工作流路径   — plan.workflow → WorkflowGraph 执行
  2. 多步编排路径 — plan.steps → 拓扑排序后逐步执行
  3. 直接对话路径 — 单个 Agent 直通

Runtime 不直接调用 Agent —— 所有执行必须经过此 Pipeline。
"""

from __future__ import annotations

import logging
from typing import Any, AsyncIterator

from haven.session.manager import SessionManager
from haven.session.models import Session
from haven.capability.registry import CapabilityRegistry
from haven.execution.request import ExecutionPlan

logger = logging.getLogger("haven.execution.pipeline")


class ExecutionPipeline:
    """执行管道 —— 将 ExecutionPlan 路由到正确的执行路径。

    持有 agents、workflow registry、session manager、context builder。
    不持有 session 状态（状态由 SessionManager 管理）。
    """

    def __init__(
        self,
        agents: dict[str, Any],
        *,
        workflow_registry: Any = None,
        session_manager: SessionManager | None = None,
        context_builder: Any = None,
        capability_registry: CapabilityRegistry | None = None,
        fact_store: Any = None,
        use_memory: bool = True,
    ) -> None:
        self.agents = agents
        self._workflow_registry = workflow_registry
        self._session_manager = session_manager
        if context_builder is None:
            from haven.runtime.context import ContextBuilder
            context_builder = ContextBuilder()
        self._context_builder = context_builder
        self._capability = capability_registry
        self._fact_store = fact_store
        self._use_memory = use_memory and fact_store is not None
        self._fallback = agents.get("general")

    # ------------------------------------------------------------------
    # 公开 API
    # ------------------------------------------------------------------

    async def run(self, plan: ExecutionPlan, task: str, session: Session) -> str:
        """根据 ExecutionPlan 选择路径并执行，返回文本结果。"""
        thread_id = session.id

        wf = plan.workflow
        if wf and self._workflow_registry and wf in self._workflow_registry.list_all():
            result = await self._via_workflow(plan, task, session)
        elif plan.steps:
            result = await self._via_steps(plan, task, session)
        else:
            agent = self._pick_agent(plan)
            sp = await self._prepare(agent, plan.skills, session, task=task)
            result = await agent.run(task, system_prompt=sp, thread_id=thread_id)

        self._after_turn(session)
        return result

    async def run_stream(
        self, plan: ExecutionPlan, task: str, session: Session,
    ) -> AsyncIterator:
        """流式执行版本。"""
        from haven.runtime.stream import StreamChunk
        thread_id = session.id
        wf = plan.workflow

        if wf and self._workflow_registry and wf in self._workflow_registry.list_all():
            yield StreamChunk(kind="status", content=f"分发执行: 工作流 {plan.workflow}")
            try:
                result = await self._via_workflow(plan, task, session)
                yield StreamChunk(kind="text", content=result)
            except Exception as exc:
                yield StreamChunk(kind="text", content=f"[错误] {exc}")
            self._after_turn(session)
            return

        if plan.steps:
            ordered = self._topological_sort(plan.steps)
            total = len(ordered)
            yield StreamChunk(kind="status", content=f"多步编排 ({total} 步) → {plan.agent_type}")
            for idx, step in enumerate(ordered, 1):
                yield StreamChunk(kind="status", content=f"[步骤 {idx}/{total}] {step.description}")
                step_task = self._build_step_task(task, step)
                agent = self._pick_for_step(step, plan.agent_type)
                step_skills = self._skills_for_step(plan.skills, step.skill)
                sp = await self._prepare(agent, step_skills, session, task=task)
                if step.order == ordered[-1].order:
                    async for chunk in agent.astream(step_task, system_prompt=sp, thread_id=thread_id):
                        yield chunk
                else:
                    await agent.run(step_task, system_prompt=sp, thread_id=thread_id)
            self._after_turn(session)
            return

        agent = self._pick_agent(plan)
        sp = await self._prepare(agent, plan.skills, session, task=task)
        yield StreamChunk(kind="status", content="分发执行: 直接对话")
        async for chunk in agent.astream(task, system_prompt=sp, thread_id=thread_id):
            yield chunk
        self._after_turn(session)

    # ------------------------------------------------------------------
    # 内部：上下文准备
    # ------------------------------------------------------------------

    async def _prepare(
        self, agent: Any, skill_names: list[str], session: Session, *, task: str = "",
    ) -> str:
        resolved = self._resolve_skill_deps(list(skill_names))
        if self._session_manager is not None:
            self._session_manager.get_or_create_state(session.id).active_skills = resolved
        return self._build_sp(agent, resolved, session, task=task)

    def _after_turn(self, session: Session) -> None:
        if self._session_manager is not None:
            self._session_manager.get_or_create_state(session.id).turn_count += 1

    # ------------------------------------------------------------------
    # 内部：路径选择
    # ------------------------------------------------------------------

    def _pick_agent(self, plan: ExecutionPlan) -> Any:
        return self.agents.get(plan.agent_type, self._fallback)

    def _pick_for_step(self, step: Any, default_type: str) -> Any:
        if step.skill:
            for at, agent in self.agents.items():
                if at in step.skill.lower():
                    return agent
        return self.agents.get(default_type, self._fallback)

    # ------------------------------------------------------------------
    # 内部：三条路径
    # ------------------------------------------------------------------

    async def _via_workflow(self, plan: ExecutionPlan, task: str, session: Session) -> str:
        wf_name = plan.workflow
        if not wf_name or self._workflow_registry is None:
            agent = self._pick_agent(plan)
            sp = await self._prepare(agent, plan.skills, session, task=task)
            return await agent.run(task, system_prompt=sp, thread_id=session.id)

        try:
            compiled_graph = self._workflow_registry.build(wf_name)
        except Exception as exc:
            logger.error("构建工作流 '%s' 失败: %s", wf_name, exc)
            return f"[错误] 工作流构建失败: {exc}"

        state = _make_workflow_state(wf_name, task, session)
        state["plan_skills"] = list(plan.skills)
        agent = self._pick_agent(plan)

        try:
            result = await compiled_graph.ainvoke(state, config={
                "configurable": {
                    "thread_id": session.id,
                    "agent": agent,
                    "agents": self.agents,
                    "context_builder": self._context_builder,
                    "dispatcher": self,
                }
            })
        except Exception as exc:
            logger.error("工作流 '%s' 执行失败: %s", wf_name, exc)
            return f"[错误] 工作流执行失败: {exc}"

        if result.get("status") == "failed":
            return "[工作流失败]\n" + "\n".join(result.get("errors", []))
        return result.get("final_output") or "(工作流完成)"

    async def _via_steps(self, plan: ExecutionPlan, task: str, session: Session) -> str:
        ordered = self._topological_sort(plan.steps)
        final = ""
        for step in ordered:
            step_task = self._build_step_task(task, step)
            agent = self._pick_for_step(step, plan.agent_type)
            step_skills = self._skills_for_step(plan.skills, step.skill)
            sp = await self._prepare(agent, step_skills, session, task=task)
            final = await agent.run(step_task, system_prompt=sp, thread_id=session.id)
        return final

    # ------------------------------------------------------------------
    # 内部：System Prompt
    # ------------------------------------------------------------------

    def _build_sp(
        self, agent: Any, skill_names: list[str], session: Session, *, task: str = "",
    ) -> str:
        skills: list[Any] = []
        seen: set[str] = set()
        if self._capability is not None:
            for name in skill_names:
                if name in seen:
                    continue
                try:
                    skills.append(self._capability.get_skill(name))
                    seen.add(name)
                except KeyError:
                    pass

        history = ""
        if self._use_memory and self._fact_store:
            facts = self._fact_store.get_all_text(session.user_id)
            if facts:
                history = f"[长期记忆]\n{facts}"

        ctx = self._context_builder.build(
            agent_prompt=getattr(agent, "agent_prompt", ""),
            skills=skills,
            task=task,
            history_summary=history,
        )
        return ctx.system_prompt

    # ------------------------------------------------------------------
    # 内部：辅助
    # ------------------------------------------------------------------

    def _resolve_skill_deps(self, names: list[str]) -> list[str]:
        if self._capability is None:
            return names
        from haven.capability.resolver import DependencyResolver
        return DependencyResolver.resolve(names, self._capability)

    def _skills_for_step(self, plan_skills: list[str], step_skill: str | None) -> list[str]:
        names = list(plan_skills)
        if step_skill and step_skill not in names:
            names.append(step_skill)
        return self._resolve_skill_deps(names)

    @staticmethod
    def _build_step_task(task: str, step: Any) -> str:
        parts = [f"原始任务: {task}", f"当前步骤: {step.description}"]
        if step.expected_output:
            parts.append(f"预期产出: {step.expected_output}")
        return "\n".join(parts)

    @staticmethod
    def _topological_sort(steps: list[Any]) -> list[Any]:
        step_map = {s.order: s for s in steps}
        in_degree = {s.order: len(s.depends_on) for s in steps}
        adj: dict[int, list[int]] = {s.order: [] for s in steps}
        for s in steps:
            for dep in s.depends_on:
                if dep in adj:
                    adj[dep].append(s.order)
        queue = [o for o, d in in_degree.items() if d == 0]
        result: list[Any] = []
        while queue:
            order = queue.pop(0)
            result.append(step_map[order])
            for nb in adj.get(order, []):
                in_degree[nb] -= 1
                if in_degree[nb] == 0:
                    queue.append(nb)
        return result


def _make_workflow_state(wf_name: str, task: str, session: Session) -> dict:
    base = {
        "task": task, "session_id": session.id,
        "messages": [], "errors": [], "completed_steps": [],
        "current_step": "", "node_outputs": {}, "node_retry_counts": {},
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
            "diagnosis": "", "recommendations": [],
        })
    return base
