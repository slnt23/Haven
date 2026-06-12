"""Planner —— 基于 LangGraph Flow 的任务规划器。

将用户输入转化为结构化的 ExecutionPlan。
规划过程本身是一个 LangGraph StateGraph：
  classify → select_skills → build_plan → validate

已删除旧 Coordinator.hardcoded_trivial_set、MD5 缓存等 —— 全部由 LLM 决定。
"""

from __future__ import annotations

import hashlib
import logging
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import StateGraph
from langgraph.graph.state import CompiledStateGraph
from typing_extensions import TypedDict

from haven.capability.registry import CapabilityRegistry
from haven.execution.request import ExecutionPlan, ExecutionRequest, PlanStep

logger = logging.getLogger("haven.execution.planner")

# ============================================================================
# Planner State (LangGraph)
# ============================================================================


class PlannerState(TypedDict, total=False):
    """Planner LangGraph 的内部状态。"""

    task: str
    intent: str
    agent_type: str
    complexity: str
    skills: list[str]
    workflow: str | None
    steps: list[dict]
    reasoning: str


# ============================================================================
# System Prompt
# ============================================================================

_PLANNER_PROMPT = """\
You are a task planner for Haven, an AI assistant with specialized agents.

## Your Job
Analyze the user's request and produce a structured execution plan in JSON.

## Output Rules
1. **goal**: Summarize the user's goal in ONE sentence.
2. **intent**: Classify into one of the available skill tags below.
3. **agent_type**: Choose the right specialist:
   - "coder"     — code generation, debugging, architecture, review
   - "researcher" — web search, data analysis, report writing, research
   - "diagnosis"  — symptom analysis, health consultation, troubleshooting
   - "general"    — casual chat, general questions, fallback
4. **complexity**: "simple" (single-turn) | "medium" (2-3 steps) | "complex" (multi-step)
5. **skills**: List skill names genuinely needed. Empty list for casual chat.
6. **workflow**: If a predefined workflow fits perfectly, use its name. Otherwise null.
7. **steps**: Break task into ordered steps (only when NOT using a workflow).

## Available Skills
{skill_menu}

## Available Workflows
{workflow_menu}
"""


# ============================================================================
# Planner
# ============================================================================


class Planner:
    """任务规划器 —— 使用 LangGraph Flow + LLM Structured Output。

    规划流程 (LangGraph):
      1. classify     → LLM 分类意图 + 复杂度
      2. select_skills → 匹配可用 Skill
      3. build_plan   → LLM 生成完整 ExecutionPlan
      4. validate     → 校验 skill/workflow 引用

    Usage::

        planner = Planner(llm, workflow_registry=..., capability_registry=...)
        plan = await planner.plan(ExecutionRequest(task="写一个排序算法"))
    """

    def __init__(
        self,
        llm: BaseChatModel,
        *,
        workflow_registry: Any = None,
        capability_registry: CapabilityRegistry | None = None,
    ) -> None:
        self._llm = llm
        self._workflow_registry = workflow_registry
        self._capability = capability_registry
        self._graph: CompiledStateGraph | None = None

    # ------------------------------------------------------------------
    # 公开 API
    # ------------------------------------------------------------------

    async def plan(self, request: ExecutionRequest) -> ExecutionPlan:
        """分析任务并生成 ExecutionPlan。

        通过 LangGraph flow 执行 classify → select_skills → build_plan → validate。
        """
        graph = self._get_graph()

        initial: PlannerState = {
            "task": request.task,
            "intent": "",
            "agent_type": "general",
            "complexity": "simple",
            "skills": [],
            "workflow": None,
            "steps": [],
            "reasoning": "",
        }

        result = await graph.ainvoke(initial)
        return self._to_execution_plan(result)

    # ------------------------------------------------------------------
    # LangGraph
    # ------------------------------------------------------------------

    def _get_graph(self) -> CompiledStateGraph:
        if self._graph is not None:
            return self._graph

        builder = StateGraph(PlannerState)

        builder.add_node("classify", self._classify_node)
        builder.add_node("select_skills", self._select_skills_node)
        builder.add_node("build_plan", self._build_plan_node)
        builder.add_node("validate", self._validate_node)

        builder.add_edge("classify", "select_skills")
        builder.add_edge("select_skills", "build_plan")
        builder.add_edge("build_plan", "validate")

        builder.set_entry_point("classify")
        builder.set_finish_point("validate")

        self._graph = builder.compile()
        return self._graph

    # ------------------------------------------------------------------
    # Nodes
    # ------------------------------------------------------------------

    async def _classify_node(self, state: PlannerState) -> dict:
        """快速分类：意图 + agent_type + complexity。"""
        task = state.get("task", "")
        prompt = f"""## Task
Analyze this user request and classify it:

User input: {task}

Output JSON with fields: intent (string), agent_type (coder|researcher|diagnosis|general), complexity (simple|medium|complex), reasoning (string)
"""
        try:
            from pydantic import BaseModel, Field

            class Classification(BaseModel):
                intent: str = ""
                agent_type: str = "general"
                complexity: str = "simple"
                reasoning: str = ""

            llm = self._llm.with_structured_output(Classification)
            result: Classification = await llm.ainvoke([
                SystemMessage(content=prompt),
                HumanMessage(content=task),
            ])
            return {
                "intent": result.intent,
                "agent_type": result.agent_type,
                "complexity": result.complexity,
                "reasoning": result.reasoning,
            }
        except Exception:
            return {"intent": "chat", "agent_type": "general", "complexity": "simple"}

    async def _select_skills_node(self, state: PlannerState) -> dict:
        """根据分类结果匹配可用 Skill。"""
        if self._capability is None:
            return {"skills": []}

        task = state.get("task", "")
        intent = state.get("intent", "")

        # 尝试按意图标签匹配
        domain = self._capability.get_domain_skills()
        matched: list[str] = []
        for name, skill in domain.items():
            if any(tag in intent.lower() or intent.lower() in tag for tag in skill.tags):
                matched.append(name)
            elif any(kw in task.lower() for kw in [skill.name, skill.description.lower()]):
                matched.append(name)

        return {"skills": matched}

    async def _build_plan_node(self, state: PlannerState) -> dict:
        """LLM 生成完整 ExecutionPlan。"""
        task = state.get("task", "")

        skill_menu = self._build_skill_menu()
        workflow_menu = self._build_workflow_menu()
        system = _PLANNER_PROMPT.format(skill_menu=skill_menu, workflow_menu=workflow_menu)

        llm_for_planning = self._llm
        if getattr(self._llm, "_llm_type", "") == "chat-deepseek":
            existing = getattr(self._llm, "extra_body", None) or {}
            llm_for_planning = self._llm.model_copy(update={
                "extra_body": {**existing, "thinking": {"type": "disabled"}},
            })

        structured = llm_for_planning.with_structured_output(ExecutionPlan)
        try:
            plan: ExecutionPlan = await structured.ainvoke([
                SystemMessage(content=system),
                HumanMessage(content=f"User request: {task}"),
            ])
        except Exception as exc:
            logger.warning("LLM 规划失败: %s", exc)
            return {
                "steps": [],
                "workflow": None,
                "reasoning": f"规划失败: {exc}",
            }

        steps_as_dicts = [s.model_dump() for s in plan.steps]
        return {
            "intent": plan.intent,
            "agent_type": plan.agent_type,
            "complexity": plan.complexity,
            "skills": list(plan.skills),
            "workflow": plan.workflow,
            "steps": steps_as_dicts,
            "reasoning": plan.reasoning,
        }

    async def _validate_node(self, state: PlannerState) -> dict:
        """校验 skill/workflow 引用。"""
        skills = list(state.get("skills", []))
        wf = state.get("workflow")

        # 校验 workflow
        if wf and self._workflow_registry:
            available_wf = self._workflow_registry.list_all()
            if wf not in available_wf:
                logger.warning("计划引用了不存在的 workflow: '%s'", wf)
                state["workflow"] = None

        # 校验 skills
        if self._capability is not None:
            available_skills = set(self._capability.list_skills().keys())
            valid = [s for s in skills if s in available_skills]
            invalid = set(skills) - set(valid)
            if invalid:
                logger.warning("计划引用了不存在的 skill: %s", invalid)
            # 依赖解析
            from haven.capability.resolver import DependencyResolver
            state["skills"] = DependencyResolver.resolve(valid, self._capability)
        else:
            state["skills"] = skills

        return {}

    # ------------------------------------------------------------------
    # 辅助
    # ------------------------------------------------------------------

    def _build_skill_menu(self) -> str:
        if self._capability is None:
            return "(无可用领域技能)"
        domain = self._capability.get_domain_skills()
        if not domain:
            return "(无可用领域技能)"
        lines: list[str] = []
        for skill in domain.values():
            deps = ", ".join(skill.dependencies) if skill.dependencies else "无"
            lines.append(
                f"### {skill.name}\n- 描述: {skill.description}\n- 标签: {', '.join(skill.tags)}\n- 依赖: {deps}"
            )
        return "\n\n".join(lines)

    def _build_workflow_menu(self) -> str:
        if self._workflow_registry is None:
            return "(无可用工作流)"
        try:
            return self._workflow_registry.get_selection_context()
        except Exception:
            return "(工作流注册表不可用)"

    @staticmethod
    def _to_execution_plan(state: PlannerState) -> ExecutionPlan:
        steps = []
        for s in state.get("steps", []):
            steps.append(PlanStep(
                order=s.get("order", 1),
                description=s.get("description", ""),
                skill=s.get("skill"),
                depends_on=s.get("depends_on", []),
                expected_output=s.get("expected_output", ""),
            ))
        return ExecutionPlan(
            goal=state.get("task", ""),
            intent=state.get("intent", "chat"),
            agent_type=state.get("agent_type", "general"),
            complexity=state.get("complexity", "simple"),
            skills=list(state.get("skills", [])),
            workflow=state.get("workflow"),
            steps=steps,
            reasoning=state.get("reasoning", ""),
        )
