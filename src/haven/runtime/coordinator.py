"""协调器 —— 仅负责任务规划，不负责执行。

Coordinator 的唯一职责是将用户输入转换为结构化的 ExecutionPlan。
执行由 Dispatcher 负责。

职责边界：
  - plan()        → Task → ExecutionPlan（LLM Structured Output）
  - _llm_plan()   → 调用 LLM 生成计划
  - _validate_plan() → 校验计划中的 skill/workflow 引用

不负责：
  - 执行（由 Dispatcher 负责）
  - Tool 选择（由 LLM Function Calling 负责）
  - Context 构建（由 ContextBuilder 负责）
"""

from __future__ import annotations

import hashlib
import logging
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from haven.skills.registry import SkillRegistry

logger = logging.getLogger("haven.coordinator")


# ============================================================================
# 结构化输出 Schema
# ============================================================================


class PlanStep(BaseModel):
    """执行计划中的单个步骤。"""

    order: int = Field(description="步骤序号，从 1 开始")
    description: str = Field(description="这一步要完成什么，自然语言描述")
    skill: str | None = Field(default=None, description="此步骤需要的 skill 名")
    depends_on: list[int] = Field(default_factory=list, description="依赖的步骤序号")
    expected_output: str = Field(default="", description="预期产出描述")


class ExecutionPlan(BaseModel):
    """Coordinator 的规划输出 —— 由 LLM Structured Output 生成。"""

    goal: str = Field(description="用户目标的一句话概括")
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
# 规划器 System Prompt
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
    """任务规划器。

    唯一公开方法：
      - plan(task) → ExecutionPlan

    不负责执行 —— 执行由 Dispatcher 负责。
    """

    # 快速路径：无需 LLM 的琐碎输入
    _TRIVIAL: set[str] = {
        "你好", "hi", "hello", "谢谢", "thanks",
        "再见", "bye", "拜拜", "在吗", "你是谁", "你能做什么",
    }

    def __init__(
        self,
        llm: BaseChatModel,
        *,
        workflow_registry: Any = None,
    ) -> None:
        self.llm = llm
        self._workflow_registry = workflow_registry
        self._plan_cache: dict[str, ExecutionPlan] = {}  # 计划缓存

    # ------------------------------------------------------------------
    # 公开 API
    # ------------------------------------------------------------------

    async def plan(self, task: str) -> ExecutionPlan:
        """分析任务并生成 ExecutionPlan。

        快速路径（琐碎输入）直接返回默认计划，不走 LLM。
        计划结果缓存 128 条，相同输入复用。
        """
        # 快速路径
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

        # 缓存检查
        cache_key = self._cache_key(task)
        if cache_key in self._plan_cache:
            return self._plan_cache[cache_key]

        # LLM 规划
        plan = await self._llm_plan(task)
        plan.skills = SkillRegistry.resolve_dependencies(plan.skills)
        plan = self._validate_plan(plan)

        # 写入缓存
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

    # ------------------------------------------------------------------
    # 快速路径
    # ------------------------------------------------------------------

    @classmethod
    def _is_trivial(cls, task: str) -> bool:
        """判断是否为无需 LLM 规划的琐碎输入。"""
        cleaned = task.strip().lower().rstrip("?!。！？")
        return cleaned in cls._TRIVIAL or len(cleaned) <= 2

    @staticmethod
    def _cache_key(task: str) -> str:
        """生成计划缓存键。"""
        return hashlib.md5(task.encode()).hexdigest()

    # ------------------------------------------------------------------
    # LLM 规划
    # ------------------------------------------------------------------

    async def _llm_plan(self, task: str) -> ExecutionPlan:
        """调用 LLM Structured Output 生成 ExecutionPlan。"""
        skill_menu = self._build_skill_menu()
        workflow_menu = self._build_workflow_menu()

        system = _PLANNER_SYSTEM_PROMPT.format(
            skill_menu=skill_menu,
            workflow_menu=workflow_menu,
        )

        # DeepSeek 模型规划时禁用 thinking（节省 token）
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
            logger.warning("LLM 规划失败: %s，回退到 general", exc)
            return ExecutionPlan(
                goal="", intent="chat", agent_type="general",
                complexity="simple", skills=[], workflow=None, steps=[],
                reasoning=f"规划失败: {exc}",
            )

        return plan

    # ------------------------------------------------------------------
    # 菜单构建
    # ------------------------------------------------------------------

    def _build_workflow_menu(self) -> str:
        """构建可用工作流列表（供 Planner LLM 选择）。"""
        if self._workflow_registry is None:
            return "(无可用工作流)"
        try:
            return self._workflow_registry.get_selection_context()
        except Exception:
            return "(工作流注册表不可用)"

    @staticmethod
    def _build_skill_menu() -> str:
        """构建领域 Skill 菜单（供 Planner LLM 选择）。"""
        domain = SkillRegistry.get_domain_skills()
        if not domain:
            return "(无可用领域技能)"

        lines: list[str] = []
        for skill in domain.values():
            deps_str = ", ".join(skill.dependencies) if skill.dependencies else "无"
            lines.append(
                f"### {skill.name}\n"
                f"- 描述: {skill.description}\n"
                f"- 标签: {', '.join(skill.tags)}\n"
                f"- 依赖: {deps_str}"
            )
        return "\n\n".join(lines)

    # ------------------------------------------------------------------
    # 计划校验
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_plan(plan: ExecutionPlan) -> ExecutionPlan:
        """校验计划中的 skill 和 workflow 引用是否存在。"""
        available = set(SkillRegistry.list_all().keys())
        valid_skills = [s for s in plan.skills if s in available]
        invalid = set(plan.skills) - set(valid_skills)
        if invalid:
            logger.warning("计划引用了不存在的 skill: %s，已过滤", invalid)
        for step in plan.steps:
            if step.skill and step.skill not in available:
                step.skill = None
        plan.skills = valid_skills
        return plan
