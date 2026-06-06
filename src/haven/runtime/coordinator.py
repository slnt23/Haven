"""Coordinator — 任务规划 + 多 Agent 调度。

在 PlannerAgent 基础上升级：plan() 不变，execute() 根据 agent_type
调度到专业 Agent (Coder/Researcher/Diagnosis/General)。
"""

from __future__ import annotations

import hashlib
import logging
from typing import Any, AsyncIterator

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from haven.skills.registry import SkillRegistry

logger = logging.getLogger("haven.coordinator")

# ============================================================================
# Structured Output Schemas
# ============================================================================


class PlanStep(BaseModel):
    """执行计划中的单步。"""

    order: int = Field(description="步骤序号，从 1 开始")
    description: str = Field(description="这一步要完成什么，自然语言描述")
    skill: str | None = Field(default=None, description="此步骤需要的 skill 名")
    depends_on: list[int] = Field(default_factory=list, description="依赖的步骤序号")
    expected_output: str = Field(default="", description="预期产出描述")


class ExecutionPlan(BaseModel):
    """Coordinator 的完整规划输出。"""

    goal: str = Field(description="用户目标的简洁概括，一句话")
    intent: str = Field(description="意图分类标签")
    agent_type: str = Field(
        default="general",
        description="调度到的 Agent 类型: coder | researcher | diagnosis | general",
    )
    complexity: str = Field(default="simple", description="simple | medium | complex")
    skills: list[str] = Field(default_factory=list, description="需要激活的 skill 名")
    workflow: str | None = Field(default=None, description="预定义工作流名")
    steps: list[PlanStep] = Field(default_factory=list, description="执行步骤")
    reasoning: str = Field(default="", description="规划理由")


# ============================================================================
# Planner System Prompt
# ============================================================================

_PLANNER_SYSTEM_PROMPT = """\
You are a task planner for Haven, an AI assistant with specialized agents.

## Your Job
Analyze the user's request and produce a structured execution plan in JSON.

## Output Rules

1. **goal**: Summarize the user's goal in ONE sentence (in the user's language).
2. **intent**: Classify into one of the available skill tags below.
3. **agent_type**: Choose the right specialist:
   - "coder"     — code generation, debugging, architecture, review
   - "researcher" — web search, data analysis, report writing, research
   - "diagnosis"  — symptom analysis, health consultation, troubleshooting
   - "general"    — casual chat, general questions, fallback
4. **complexity**:
   - "simple"  — single-turn
   - "medium"  — 2-3 steps
   - "complex" — multi-step with dependencies
5. **skills**: List skill names genuinely needed. Empty list for casual chat.
6. **workflow**: If a predefined workflow fits perfectly, use its name. Otherwise null.
7. **steps**: Break task into ordered steps.

## Important
- For casual chat: agent_type="general", skills=[], steps=[].
- Only select skills/workflows from the menus below. Do NOT invent names.

## Available Skills
{skill_menu}

## Available Workflows
{workflow_menu}
"""


# ============================================================================
# Coordinator
# ============================================================================


class Coordinator:
    """任务规划 + 多 Agent 调度。

    职责:
      1. plan()   — LLM Structured Output → ExecutionPlan (含 agent_type)
      2. execute() — 根据 agent_type 调度到专业 Agent
      3. execute_stream() — 流式版本
    """

    def __init__(
        self,
        agents: dict[str, Any],
        llm: BaseChatModel,
        *,
        workflow_registry: Any = None,
        state: Any = None,
    ):
        self.agents = agents
        self.llm = llm
        self._workflow_registry = workflow_registry
        self.state = state  # RuntimeState (shared across agents)
        self._plan_cache: dict[str, ExecutionPlan] = {}
        self._fallback_agent = agents.get("general")

    @property
    def runtime(self):
        """兼容旧接口 — 返回 general agent (仅用于 workflow 节点)。"""
        return self._fallback_agent

    # ==================================================================
    # 公开 API
    # ==================================================================

    async def plan(self, task: str) -> ExecutionPlan:
        """分析任务并生成 ExecutionPlan。"""
        if self._is_trivial(task):
            return ExecutionPlan(
                goal="日常对话",
                intent="chat",
                agent_type="general",
                complexity="simple",
                skills=[],
                workflow=None,
                steps=[],
                reasoning="简单社交对话",
            )

        cache_key = self._cache_key(task)
        if cache_key in self._plan_cache:
            return self._plan_cache[cache_key]

        plan = await self._llm_plan(task)
        plan.skills = SkillRegistry.resolve_dependencies(plan.skills)
        plan = self._validate_plan(plan)

        self._plan_cache[cache_key] = plan
        if len(self._plan_cache) > 128:
            first = next(iter(self._plan_cache))
            del self._plan_cache[first]

        logger.info(
            "Plan: intent=%s agent=%s complexity=%s skills=%s workflow=%s steps=%d",
            plan.intent, plan.agent_type, plan.complexity,
            plan.skills, plan.workflow, len(plan.steps),
        )
        return plan

    async def execute(self, task: str) -> str:
        """规划 + 调度执行。"""
        plan = await self.plan(task)

        # 路径 1: 工作流
        if plan.workflow and self._workflow_registry:
            return await self._execute_via_workflow(plan, task)

        # 路径 2: 多步编排
        if plan.steps:
            return await self._execute_steps(plan, task)

        # 路径 3: 简单对话 → Agent
        agent = self.agents.get(plan.agent_type, self._fallback_agent)
        return await agent.run(task)

    async def execute_stream(self, task: str) -> AsyncIterator[str]:
        """流式规划 + 执行。"""
        plan = await self.plan(task)

        if plan.workflow and self._workflow_registry:
            try:
                result = await self._execute_via_workflow(plan, task)
                yield result
            except Exception as exc:
                yield f"[错误] 工作流执行失败: {exc}"
            return

        if plan.steps:
            ordered = self._topological_sort(plan.steps)
            step_outputs: dict[int, str] = {}
            for step in ordered:
                step_task = f"原始任务: {task}\n当前步骤: {step.description}"
                if step.expected_output:
                    step_task += f"\n预期产出: {step.expected_output}"

                agent = self._pick_agent_for_step(step, plan.agent_type)

                if step.order == ordered[-1].order:
                    collected: list[str] = []
                    async for chunk in agent.astream(step_task):
                        collected.append(chunk)
                        yield chunk
                    step_outputs[step.order] = "".join(collected)
                else:
                    result = await agent.run(step_task)
                    step_outputs[step.order] = result
            return

        # 简单对话 → 流式
        agent = self.agents.get(plan.agent_type, self._fallback_agent)
        async for chunk in agent.astream(task):
            yield chunk

    # ==================================================================
    # 快速路径
    # ==================================================================

    _TRIVIAL: set[str] = {
        "你好", "hi", "hello", "谢谢", "thanks",
        "再见", "bye", "拜拜", "在吗", "你是谁", "你能做什么",
    }

    @classmethod
    def _is_trivial(cls, task: str) -> bool:
        cleaned = task.strip().lower().rstrip("?!。！？")
        return cleaned in cls._TRIVIAL or len(cleaned) <= 2

    @staticmethod
    def _cache_key(task: str) -> str:
        return hashlib.md5(task.encode()).hexdigest()

    # ==================================================================
    # Agent 选择
    # ==================================================================

    def _pick_agent_for_step(self, step: PlanStep, default_type: str):
        """根据 step.skill 选择合适的 Agent。"""
        if step.skill:
            # skill 到 agent_type 的启发式映射
            for agent_type, agent in self.agents.items():
                if agent_type in step.skill.lower():
                    return agent
        return self.agents.get(default_type, self._fallback_agent)

    # ==================================================================
    # LLM 规划
    # ==================================================================

    async def _llm_plan(self, task: str) -> ExecutionPlan:
        skill_menu = SkillRegistry.get_selection_context()
        workflow_menu = self._get_workflow_menu()

        system = _PLANNER_SYSTEM_PROMPT.format(
            skill_menu=skill_menu,
            workflow_menu=workflow_menu,
        )

        llm_for_planning = self.llm
        if getattr(self.llm, "_llm_type", "") == "chat-deepseek":
            existing_extra = getattr(self.llm, "extra_body", None) or {}
            llm_for_planning = self.llm.model_copy(update={
                "extra_body": {**existing_extra, "thinking": {"type": "disabled"}},
            })

        structured_llm = llm_for_planning.with_structured_output(ExecutionPlan)

        try:
            plan: ExecutionPlan = await structured_llm.ainvoke([
                SystemMessage(content=system),
                HumanMessage(content=f"User request: {task}"),
            ])
        except Exception as exc:
            logger.warning("LLM planning failed: %s, falling back to chat", exc)
            return ExecutionPlan(
                goal="", intent="chat", agent_type="general",
                complexity="simple", skills=[], workflow=None, steps=[],
                reasoning=f"规划失败: {exc}",
            )

        return plan

    def _get_workflow_menu(self) -> str:
        if self._workflow_registry is None:
            return "(无可用工作流)"
        try:
            return self._workflow_registry.get_selection_context()
        except Exception:
            return "(工作流注册表不可用)"

    # ==================================================================
    # 验证
    # ==================================================================

    @staticmethod
    def _validate_plan(plan: ExecutionPlan) -> ExecutionPlan:
        available = set(SkillRegistry.list_all().keys())
        valid_skills = [s for s in plan.skills if s in available]
        invalid = set(plan.skills) - set(valid_skills)
        if invalid:
            logger.warning("Plan 引用了不存在的 skill: %s，已过滤", invalid)
        for step in plan.steps:
            if step.skill and step.skill not in available:
                step.skill = None
        plan.skills = valid_skills
        return plan

    # ==================================================================
    # 路径 1: 工作流
    # ==================================================================

    async def _execute_via_workflow(self, plan: ExecutionPlan, task: str) -> str:
        wf_name = plan.workflow
        if not wf_name or self._workflow_registry is None:
            agent = self.agents.get(plan.agent_type, self._fallback_agent)
            return await agent.run(task)

        try:
            compiled_graph = self._workflow_registry.build(wf_name)
        except Exception as exc:
            logger.error("构建工作流 '%s' 失败: %s", wf_name, exc)
            return f"[错误] 工作流 '{wf_name}' 构建失败: {exc}"

        state = self._make_state(wf_name, task)
        agent = self.agents.get(plan.agent_type, self._fallback_agent)

        try:
            result = await compiled_graph.ainvoke(
                state,
                config={
                    "configurable": {
                        "thread_id": self.state.session_id,
                        "agent": agent,
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

    def _make_state(self, wf_name: str, task: str) -> dict:
        base = {
            "task": task,
            "session_id": self.state.session_id,
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

    # ==================================================================
    # 路径 2: 自编排多步
    # ==================================================================

    async def _execute_steps(self, plan: ExecutionPlan, task: str) -> str:
        ordered = self._topological_sort(plan.steps)
        step_outputs: dict[int, str] = {}
        final = ""

        for step in ordered:
            step_task = f"原始任务: {task}\n当前步骤: {step.description}"
            if step.expected_output:
                step_task += f"\n预期产出: {step.expected_output}"

            agent = self._pick_agent_for_step(step, plan.agent_type)
            result = await agent.run(step_task)
            step_outputs[step.order] = result
            final = result

        return final

    # ==================================================================
    # 工具方法
    # ==================================================================

    def switch_model(self, model_name: str) -> str:
        for agent in self.agents.values():
            if hasattr(agent, "llm"):
                from haven.core.llm import create_llm
                agent.llm = create_llm(model_name)
                agent._agent = None
        self.llm = self._fallback_agent.llm if self._fallback_agent else self.llm
        return model_name

    def reset(self) -> None:
        self.state.reset_turn()
        for agent in self.agents.values():
            agent.reset()

    @staticmethod
    def _topological_sort(steps: list[PlanStep]) -> list[PlanStep]:
        step_map = {s.order: s for s in steps}
        in_degree = {s.order: len(s.depends_on) for s in steps}
        adj: dict[int, list[int]] = {s.order: [] for s in steps}
        for s in steps:
            for dep in s.depends_on:
                if dep in adj:
                    adj[dep].append(s.order)
        queue = [o for o, d in in_degree.items() if d == 0]
        result: list[PlanStep] = []
        while queue:
            order = queue.pop(0)
            result.append(step_map[order])
            for nb in adj.get(order, []):
                in_degree[nb] -= 1
                if in_degree[nb] == 0:
                    queue.append(nb)
        return result
