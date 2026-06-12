"""调度器 —— 接收 ExecutionPlan，路由到正确的执行路径。

Dispatcher 是 Coordinator（规划）和 BaseAgent（执行）之间的桥梁。
Session 状态由 SessionManager 管理，Dispatcher 不持有 session 状态。
"""

from __future__ import annotations

import logging
from typing import Any, AsyncIterator

from haven.session.manager import SessionManager
from haven.session.models import Session
from haven.capability.registry import CapabilityRegistry
from haven.runtime.context import ContextBuilder
from haven.runtime.stream import StreamChunk

logger = logging.getLogger("haven.dispatcher")


class Dispatcher:
    """执行路径调度器。

    Session 状态通过 SessionManager 管理。
    """

    def __init__(
        self,
        agents: dict[str, Any],
        *,
        workflow_registry: Any = None,
        session_manager: SessionManager | None = None,
        context_builder: ContextBuilder | None = None,
        capability_registry: CapabilityRegistry | None = None,
        fact_store: Any = None,
        use_memory: bool = True,
    ) -> None:
        self.agents = agents
        self._workflow_registry = workflow_registry
        self._session_manager = session_manager
        self._context_builder = context_builder or ContextBuilder()
        self._capability = capability_registry
        self._fact_store = fact_store
        self._use_memory = use_memory and fact_store is not None
        self._fallback_agent = agents.get("general")

    # ------------------------------------------------------------------
    # 公开 API
    # ------------------------------------------------------------------

    async def dispatch(self, plan: Any, task: str, session: Session) -> str:
        """根据 ExecutionPlan 选择路径并执行。"""
        thread_id = session.id
        wf = plan.workflow
        if wf and self._workflow_registry and wf in self._workflow_registry.list_all():
            return await self._execute_via_workflow(plan, task, session)

        if plan.steps:
            return await self._execute_steps(plan, task, session)

        agent = self._pick_agent(plan)
        system_prompt = await self._prepare_agent(agent, plan.skills, session, task=task)
        result = await agent.run(task, system_prompt=system_prompt, thread_id=thread_id)
        self._after_turn(session)
        return result

    async def dispatch_stream(
        self, plan: Any, task: str, session: Session,
    ) -> AsyncIterator[StreamChunk]:
        """流式版本的 dispatch。"""
        thread_id = session.id
        wf = plan.workflow
        if wf and self._workflow_registry and wf in self._workflow_registry.list_all():
            yield StreamChunk(kind="status", content=f"分发执行: 工作流 {plan.workflow}")
            try:
                result = await self._execute_via_workflow(plan, task, session)
                yield StreamChunk(kind="text", content=result)
            except Exception as exc:
                yield StreamChunk(kind="text", content=f"[错误] 工作流执行失败: {exc}")
            self._after_turn(session)
            return

        if plan.steps:
            ordered = self._topological_sort(plan.steps)
            total = len(ordered)
            yield StreamChunk(
                kind="status",
                content=f"分发执行: 多步编排 ({total} 步) → {plan.agent_type}",
            )
            step_outputs: dict[int, str] = {}
            for idx, step in enumerate(ordered, 1):
                yield StreamChunk(
                    kind="status",
                    content=f"[步骤 {idx}/{total}] {step.description}",
                )
                step_task = self._build_step_task(task, step)
                agent = self._pick_agent_for_step(step, plan.agent_type)
                step_skills = self._skills_for_step(plan.skills, step.skill)
                system_prompt = await self._prepare_agent(agent, step_skills, session, task=task)

                if step.order == ordered[-1].order:
                    collected: list[str] = []
                    async for chunk in agent.astream(step_task, system_prompt=system_prompt, thread_id=thread_id):
                        if chunk.kind == "text":
                            collected.append(chunk.content)
                        yield chunk
                    step_outputs[step.order] = "".join(collected)
                else:
                    result = await agent.run(step_task, system_prompt=system_prompt, thread_id=thread_id)
                    step_outputs[step.order] = result
            self._after_turn(session)
            return

        agent = self._pick_agent(plan)
        system_prompt = await self._prepare_agent(agent, plan.skills, session, task=task)
        yield StreamChunk(kind="status", content="分发执行: 直接对话")
        async for chunk in agent.astream(task, system_prompt=system_prompt, thread_id=thread_id):
            yield chunk
        self._after_turn(session)

    # ------------------------------------------------------------------
    # 上下文准备
    # ------------------------------------------------------------------

    async def _prepare_agent(
        self,
        agent: Any,
        skill_names: list[str],
        session: Session,
        *,
        task: str = "",
    ) -> str:
        """为 Agent 构建 system_prompt，并更新 session state。"""
        resolved = self._resolve_skill_deps(list(skill_names))
        if self._session_manager is not None:
            state = self._session_manager.get_or_create_state(session.id)
            state.active_skills = resolved
        return self._build_system_prompt(agent, resolved, session, task=task)

    def _after_turn(self, session: Session) -> None:
        """每轮对话后更新 turn_count。"""
        if self._session_manager is not None:
            state = self._session_manager.get_or_create_state(session.id)
            state.turn_count += 1

    # ------------------------------------------------------------------
    # 内部：路径选择
    # ------------------------------------------------------------------

    def _pick_agent(self, plan: Any) -> Any:
        return self.agents.get(plan.agent_type, self._fallback_agent)

    def _pick_agent_for_step(self, step: Any, default_type: str) -> Any:
        if step.skill:
            for agent_type, agent in self.agents.items():
                if agent_type in step.skill.lower():
                    return agent
        return self.agents.get(default_type, self._fallback_agent)

    # ------------------------------------------------------------------
    # 内部：三条执行路径
    # ------------------------------------------------------------------

    async def _execute_via_workflow(self, plan: Any, task: str, session: Session) -> str:
        wf_name = plan.workflow
        if not wf_name or self._workflow_registry is None:
            agent = self._pick_agent(plan)
            system_prompt = await self._prepare_agent(agent, plan.skills, session, task=task)
            return await agent.run(task, system_prompt=system_prompt, thread_id=session.id)

        try:
            compiled_graph = self._workflow_registry.build(wf_name)
        except Exception as exc:
            logger.error("构建工作流 '%s' 失败: %s", wf_name, exc)
            return f"[错误] 工作流 '{wf_name}' 构建失败: {exc}"

        state = self._make_workflow_state(wf_name, task, session)
        state["plan_skills"] = list(plan.skills) if plan.skills else []
        agent = self._pick_agent(plan)

        try:
            result = await compiled_graph.ainvoke(
                state,
                config={
                    "configurable": {
                        "thread_id": session.id,
                        "agent": agent,
                        "agents": self.agents,
                        "context_builder": self._context_builder,
                        "dispatcher": self,
                    }
                },
            )
        except Exception as exc:
            logger.error("工作流 '%s' 执行失败: %s", wf_name, exc)
            return f"[错误] 工作流执行失败: {exc}"

        if result.get("status") == "failed":
            errors = result.get("errors", [])
            logger.warning("工作流 '%s' 失败: %s", wf_name, errors)
            return "[工作流失败]\n" + "\n".join(errors)

        logger.info("工作流 '%s' 完成", wf_name)
        return result.get("final_output") or "(工作流完成，无输出)"

    async def _execute_steps(self, plan: Any, task: str, session: Session) -> str:
        ordered = self._topological_sort(plan.steps)
        final = ""

        for step in ordered:
            step_task = self._build_step_task(task, step)
            agent = self._pick_agent_for_step(step, plan.agent_type)
            step_skills = self._skills_for_step(plan.skills, step.skill)
            system_prompt = await self._prepare_agent(agent, step_skills, session, task=task)
            final = await agent.run(step_task, system_prompt=system_prompt, thread_id=session.id)

        return final

    # ------------------------------------------------------------------
    # 内部：System Prompt 构建
    # ------------------------------------------------------------------

    def _build_system_prompt(
        self,
        agent: Any,
        skill_names: list[str],
        session: Session,
        *,
        task: str = "",
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

        history_summary = ""
        if self._use_memory and self._fact_store:
            facts_text = self._fact_store.get_all_text(session.user_id)
            if facts_text:
                history_summary = f"[长期记忆]\n{facts_text}"

        ctx = self._context_builder.build(
            agent_prompt=getattr(agent, "agent_prompt", ""),
            skills=skills,
            task=task,
            history_summary=history_summary,
        )
        return ctx.system_prompt

    # ------------------------------------------------------------------
    # 内部：辅助方法
    # ------------------------------------------------------------------

    def _resolve_skill_deps(self, names: list[str]) -> list[str]:
        if self._capability is None:
            return list(names)
        from haven.capability.resolver import DependencyResolver
        return DependencyResolver.resolve(list(names), self._capability)

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
        in_degree: dict[int, int] = {s.order: len(s.depends_on) for s in steps}
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

    def _make_workflow_state(self, wf_name: str, task: str, session: Session) -> dict:
        base = {
            "task": task,
            "session_id": session.id,
            "messages": [],
            "errors": [],
            "completed_steps": [],
            "current_step": "",
            "node_outputs": {},
            "node_retry_counts": {},
            "max_retries_per_node": 3,
            "status": "pending",
            "final_output": "",
            "started_at": 0.0,
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
