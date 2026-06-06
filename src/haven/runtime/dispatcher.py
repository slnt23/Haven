"""调度器 —— 接收 ExecutionPlan，路由到正确的执行路径。

Dispatcher 是 Coordinator（规划）和 BaseAgent（执行）之间的桥梁。
它不负责规划，只负责"怎么执行这个计划"。

三条执行路径：
  1. 工作流路径   — plan.workflow 存在 → WorkflowGraph 执行
  2. 多步编排路径 — plan.steps 非空 → 拓扑排序后逐步执行
  3. 直接对话路径 — 其余情况 → 单个 Agent 直通
"""

from __future__ import annotations

import logging
from typing import Any, AsyncIterator

from haven.runtime.context import ContextBuilder
from haven.skills.registry import SkillRegistry

logger = logging.getLogger("haven.dispatcher")


class Dispatcher:
    """执行路径调度器。

    职责：
      - 根据 ExecutionPlan 选择执行路径（Workflow / 多步 / 直接）
      - 构建 system_prompt（通过 ContextBuilder）
      - 调用 Agent 执行

    不负责：
      - 任务规划（由 Coordinator 负责）
      - Tool 选择（由 LLM Function Calling 负责）
    """

    def __init__(
        self,
        agents: dict[str, Any],
        *,
        workflow_registry: Any = None,
        state: Any = None,
        context_builder: ContextBuilder | None = None,
        fact_store: Any = None,
        use_memory: bool = True,
    ) -> None:
        self.agents = agents  # name → BaseAgent
        self._workflow_registry = workflow_registry  # WorkflowRegistry
        self.state = state  # RuntimeState
        self._context_builder = context_builder or ContextBuilder()
        self._fact_store = fact_store
        self._use_memory = use_memory and fact_store is not None
        self._fallback_agent = agents.get("general")

    # ------------------------------------------------------------------
    # 公开 API
    # ------------------------------------------------------------------

    async def dispatch(self, plan: Any, task: str) -> str:
        """根据 ExecutionPlan 选择路径并执行。"""
        # 路径 1：工作流
        if plan.workflow and self._workflow_registry:
            return await self._execute_via_workflow(plan, task)

        # 路径 2：多步编排
        if plan.steps:
            return await self._execute_steps(plan, task)

        # 路径 3：直接对话
        agent = self._pick_agent(plan)
        system_prompt = await self.prepare_agent(agent, plan.skills, task=task)
        return await agent.run(task, system_prompt=system_prompt)

    async def dispatch_stream(self, plan: Any, task: str) -> AsyncIterator[str]:
        """流式版本的 dispatch。"""
        # 路径 1：工作流（工作流暂不支持流式，整体执行后一次性返回）
        if plan.workflow and self._workflow_registry:
            try:
                result = await self._execute_via_workflow(plan, task)
                yield result
            except Exception as exc:
                yield f"[错误] 工作流执行失败: {exc}"
            return

        # 路径 2：多步编排（仅最后一步流式输出）
        if plan.steps:
            ordered = self._topological_sort(plan.steps)
            step_outputs: dict[int, str] = {}
            for step in ordered:
                step_task = self._build_step_task(task, step)
                agent = self._pick_agent_for_step(step, plan.agent_type)
                step_skills = self._skills_for_step(plan.skills, step.skill)
                system_prompt = await self.prepare_agent(agent, step_skills, task=task)

                if step.order == ordered[-1].order:
                    collected: list[str] = []
                    async for chunk in agent.astream(step_task, system_prompt=system_prompt):
                        collected.append(chunk)
                        yield chunk
                    step_outputs[step.order] = "".join(collected)
                else:
                    result = await agent.run(step_task, system_prompt=system_prompt)
                    step_outputs[step.order] = result
            return

        # 路径 3：直接对话流式
        agent = self._pick_agent(plan)
        system_prompt = await self.prepare_agent(agent, plan.skills, task=task)
        async for chunk in agent.astream(task, system_prompt=system_prompt):
            yield chunk

    # ------------------------------------------------------------------
    # 上下文准备（供 Workflow 节点复用）
    # ------------------------------------------------------------------

    async def prepare_agent(
        self,
        agent: Any,
        skill_names: list[str],
        *,
        task: str = "",
    ) -> str:
        """为 Agent 构建 system_prompt。

        Skill 仅影响 system_prompt 内容。工具在 Agent 创建时已绑定，
        LLM 自行决定调用哪个 —— 此处不做任何工具解析。
        """
        resolved = SkillRegistry.resolve_dependencies(list(skill_names))
        if self.state:
            self.state.active_skills = resolved
        return self._build_system_prompt(agent, resolved, task=task)

    # ------------------------------------------------------------------
    # 内部：路径选择
    # ------------------------------------------------------------------

    def _pick_agent(self, plan: Any) -> Any:
        """根据 plan.agent_type 选择 Agent。"""
        return self.agents.get(plan.agent_type, self._fallback_agent)

    def _pick_agent_for_step(self, step: Any, default_type: str) -> Any:
        """根据 step.skill 选择合适的 Agent（启发式）。"""
        if step.skill:
            for agent_type, agent in self.agents.items():
                if agent_type in step.skill.lower():
                    return agent
        return self.agents.get(default_type, self._fallback_agent)

    # ------------------------------------------------------------------
    # 内部：三条执行路径
    # ------------------------------------------------------------------

    async def _execute_via_workflow(self, plan: Any, task: str) -> str:
        """路径 1：工作流执行。"""
        wf_name = plan.workflow
        if not wf_name or self._workflow_registry is None:
            agent = self._pick_agent(plan)
            system_prompt = await self.prepare_agent(agent, plan.skills, task=task)
            return await agent.run(task, system_prompt=system_prompt)

        try:
            compiled_graph = self._workflow_registry.build(wf_name)
        except Exception as exc:
            logger.error("构建工作流 '%s' 失败: %s", wf_name, exc)
            return f"[错误] 工作流 '{wf_name}' 构建失败: {exc}"

        state = self._make_workflow_state(wf_name, task)
        agent = self._pick_agent(plan)

        try:
            result = await compiled_graph.ainvoke(
                state,
                config={
                    "configurable": {
                        "thread_id": self.state.session_id if self.state else "default",
                        "agent": agent,
                        "agents": self.agents,
                        "context_builder": self._context_builder,
                        "dispatcher": self,  # 供 Workflow 节点复用
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

    async def _execute_steps(self, plan: Any, task: str) -> str:
        """路径 2：多步编排执行。"""
        ordered = self._topological_sort(plan.steps)
        final = ""

        for step in ordered:
            step_task = self._build_step_task(task, step)
            agent = self._pick_agent_for_step(step, plan.agent_type)
            step_skills = self._skills_for_step(plan.skills, step.skill)
            system_prompt = await self.prepare_agent(agent, step_skills, task=task)
            final = await agent.run(step_task, system_prompt=system_prompt)

        return final

    # ------------------------------------------------------------------
    # 内部：System Prompt 构建
    # ------------------------------------------------------------------

    def _build_system_prompt(
        self,
        agent: Any,
        skill_names: list[str],
        *,
        task: str = "",
    ) -> str:
        """通过 ContextBuilder 组装 system_prompt。"""
        skills: list[Any] = []
        seen: set[str] = set()
        for name in skill_names:
            if name in seen:
                continue
            try:
                skills.append(SkillRegistry.get(name))
                seen.add(name)
            except KeyError:
                pass

        history_summary = ""
        if self._use_memory and self._fact_store and self.state:
            facts_text = self._fact_store.get_all_text(self.state.entity_name)
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

    @staticmethod
    def _skills_for_step(plan_skills: list[str], step_skill: str | None) -> list[str]:
        """合并 plan 级与 step 级 skill 并解析依赖。"""
        names = list(plan_skills)
        if step_skill and step_skill not in names:
            names.append(step_skill)
        return SkillRegistry.resolve_dependencies(names)

    @staticmethod
    def _build_step_task(task: str, step: Any) -> str:
        """为多步执行的单步构建 prompt。"""
        parts = [f"原始任务: {task}", f"当前步骤: {step.description}"]
        if step.expected_output:
            parts.append(f"预期产出: {step.expected_output}")
        return "\n".join(parts)

    @staticmethod
    def _topological_sort(steps: list[Any]) -> list[Any]:
        """拓扑排序 —— 确保依赖关系正确的执行顺序。"""
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

    def _make_workflow_state(self, wf_name: str, task: str) -> dict:
        """构建工作流初始状态字典。"""
        base = {
            "task": task,
            "session_id": self.state.session_id if self.state else "default",
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
        # 按工作流类型附加特定字段
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
