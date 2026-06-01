"""PlannerAgent — 任务规划层。

在 AgentRuntime 之上，负责理解、拆解、规划任务。
一次 LLM 调用完成：意图分类 + Skill 选择 + 任务拆解 + Workflow 匹配。

替代 V1 的 OrchestratorAgent 硬编码 4 分类路由。
"""

from __future__ import annotations

import hashlib
import logging
from typing import Any, AsyncIterator

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from haven.runtime.runtime import AgentRuntime
from haven.skills.registry import SkillRegistry

logger = logging.getLogger("haven.planner")

# ============================================================================
# Structured Output Schemas
# ============================================================================


class PlanStep(BaseModel):
    """执行计划中的单步。"""

    order: int = Field(description="步骤序号，从 1 开始")
    description: str = Field(description="这一步要完成什么，自然语言描述")
    skill: str | None = Field(
        default=None, description="此步骤需要的 skill 名。null = 使用默认人格"
    )
    depends_on: list[int] = Field(
        default_factory=list,
        description="依赖的步骤序号列表。空列表 = 可立即执行",
    )
    expected_output: str = Field(default="", description="预期产出描述")


class ExecutionPlan(BaseModel):
    """PlannerAgent 的完整规划输出。"""

    goal: str = Field(description="用户目标的简洁概括，一句话")
    intent: str = Field(
        description="意图分类标签。从 skill tags 中动态获取："
        "development, medical, technical, chat, data, devops, writing"
    )
    complexity: str = Field(
        default="simple",
        description="任务复杂度: simple (单轮), medium (2-3步), complex (多步+依赖)",
    )
    skills: list[str] = Field(
        default_factory=list,
        description="需要激活的 skill 名列表。空 = 只用默认人格",
    )
    workflow: str | None = Field(
        default=None,
        description="预定义工作流名。非 null 时 WorkflowEngine 接管执行",
    )
    steps: list[PlanStep] = Field(
        default_factory=list,
        description="执行步骤。单步任务 = 1 个元素；简单对话 = 空列表",
    )
    reasoning: str = Field(default="", description="规划理由，用于日志和调试")


# ============================================================================
# Planner System Prompt
# ============================================================================

_PLANNER_SYSTEM_PROMPT = """\
You are a task planner for Haven, an AI assistant.

## Your Job
Analyze the user's request and produce a structured execution plan in JSON.

## Output Rules

1. **goal**: Summarize the user's goal in ONE sentence (in the user's language).
2. **intent**: Classify into one of the available skill tags below.
   If no specific domain matches, use "chat".
3. **complexity**:
   - "simple"  — single-turn, one skill or no skill needed
   - "medium"  — 2-3 steps, sequential
   - "complex" — multi-step with dependencies, multiple skills
4. **skills**: List skill names genuinely needed. Empty list for casual chat.
5. **workflow**: If a predefined workflow fits perfectly, use its name. Otherwise null.
6. **steps**: Break the task into ordered steps. Each step has:
   - order: sequential number (1-based)
   - description: what this step does (in the user's language)
   - skill: which skill to use (null if no specific skill)
   - depends_on: list of step orders that must finish first
   - expected_output: what this step should produce

## Important
- For casual chat / simple questions: complexity="simple", skills=[], steps=[].
- Only select skills from the menu below. Do NOT invent skill names.
- Only select workflows from the menu below. Do NOT invent workflow names.
- A step's skill MUST appear in the skills list.
- Order skills by relevance, then by dependency.

## Available Skills
{skill_menu}

## Available Workflows
{workflow_menu}
"""


# ============================================================================
# PlannerAgent
# ============================================================================


class PlannerAgent:
    """任务规划层。组合 SkillSelector，委托 AgentRuntime 执行。

    职责:
      1. 理解任务 — LLM Structured Output 分类 + 复杂度评估
      2. 拆解任务 — 将复杂任务分解为有序步骤
      3. 生成计划 — 输出 ExecutionPlan
      4. 选择 Skill — 内嵌到规划 LLM 调用中
      5. 委托执行 — 调用 Runtime.run() 或 WorkflowEngine（后续阶段）

    用法::

        runtime = AgentRuntime()
        runtime.init_llm()
        planner = PlannerAgent(runtime)
        result = await planner.execute("帮我写一个爬虫")
    """

    def __init__(
        self,
        runtime: AgentRuntime,
        *,
        workflow_registry: Any = None,
    ):
        self.runtime = runtime
        self._workflow_registry = workflow_registry
        self._plan_cache: dict[str, ExecutionPlan] = {}

    @property
    def llm(self) -> BaseChatModel | None:
        return self.runtime.llm

    # ==================================================================
    # 公开 API
    # ==================================================================

    async def plan(self, task: str) -> ExecutionPlan:
        """分析任务并生成 ExecutionPlan。不修改 Runtime 状态。"""
        # 快速路径
        if self._is_trivial(task):
            return ExecutionPlan(
                goal="日常对话",
                intent="chat",
                complexity="simple",
                skills=[],
                workflow=None,
                steps=[],
                reasoning="简单社交对话",
            )

        # 缓存
        cache_key = self._cache_key(task)
        if cache_key in self._plan_cache:
            return self._plan_cache[cache_key]

        # LLM 规划
        plan = await self._llm_plan(task)

        # 依赖解析
        plan.skills = SkillRegistry.resolve_dependencies(plan.skills)

        # 验证
        plan = self._validate_plan(plan)

        self._plan_cache[cache_key] = plan
        if len(self._plan_cache) > 128:
            first = next(iter(self._plan_cache))
            del self._plan_cache[first]

        logger.info(
            "Plan: intent=%s complexity=%s skills=%s workflow=%s steps=%d",
            plan.intent,
            plan.complexity,
            plan.skills,
            plan.workflow,
            len(plan.steps),
        )
        return plan

    async def execute(self, task: str) -> str:
        """一步完成规划+执行。最常用的入口。"""
        plan = await self.plan(task)

        # 路径 1: 有 workflow → WorkflowEngine（后续阶段实现）
        if plan.workflow and self._workflow_registry:
            return await self._execute_via_workflow(plan, task)

        # 路径 2: 有步骤但无 workflow → Planner 顺序编排 Runtime
        if plan.steps:
            return await self._execute_steps(plan, task)

        # 路径 3: 无步骤（简单对话）→ Runtime 直通
        return await self.runtime.run(
            task,
            use_memory=True,
        )

    async def execute_stream(self, task: str) -> AsyncIterator[str]:
        """流式规划+执行。规划非流式，执行阶段逐 token 输出。

        三路径流式支持：
          - 简单对话 → Runtime.astream() 直通
          - 多步任务 → 每步 Runtime.astream()
          - 工作流 → 首节点 Runtime.astream()
        """
        plan = await self.plan(task)

        # 路径 1: 工作流（非流式 DAG 执行，yield 最终结果）
        if plan.workflow and self._workflow_registry:
            try:
                result = await self._execute_via_workflow(plan, task)
                yield result
            except Exception as exc:
                yield f"[错误] 工作流执行失败: {exc}"
            return

        # 路径 2: 多步编排
        if plan.steps:
            ordered = self._topological_sort(plan.steps)
            step_outputs: dict[int, str] = {}
            for step in ordered:
                skill_objs = self._load_skills([step.skill] if step.skill else [])
                prev_results: dict[str, str] = {}
                for dep in step.depends_on:
                    if dep in step_outputs:
                        prev_results[f"step_{dep}"] = step_outputs[dep]

                step_task = f"原始任务: {task}\n当前步骤: {step.description}"
                if step.expected_output:
                    step_task += f"\n预期产出: {step.expected_output}"

                # 最后一步流式输出，前面的步骤非流式
                if step.order == ordered[-1].order:
                    collected: list[str] = []
                    async for chunk in self.runtime.astream(
                        step_task,
                        active_skills=skill_objs,
                        use_memory=True,
                        tool_results=prev_results or None,
                    ):
                        collected.append(chunk)
                        yield chunk
                    step_outputs[step.order] = "".join(collected)
                else:
                    result = await self.runtime.run(
                        step_task,
                        active_skills=skill_objs,
                        use_memory=True,
                        tool_results=prev_results or None,
                    )
                    step_outputs[step.order] = result
            return

        # 路径 3: 简单对话 → 流式直通
        async for chunk in self.runtime.astream(task, use_memory=True):
            yield chunk

    # ==================================================================
    # 快速路径
    # ==================================================================

    _TRIVIAL: set[str] = {
        "你好",
        "hi",
        "hello",
        "谢谢",
        "thanks",
        "再见",
        "bye",
        "拜拜",
        "在吗",
        "你是谁",
        "你能做什么",
    }

    @classmethod
    def _is_trivial(cls, task: str) -> bool:
        cleaned = task.strip().lower().rstrip("?!。！？")
        return cleaned in cls._TRIVIAL or len(cleaned) <= 2

    @staticmethod
    def _cache_key(task: str) -> str:
        return hashlib.md5(task.encode()).hexdigest()

    # ==================================================================
    # LLM 规划
    # ==================================================================

    async def _llm_plan(self, task: str) -> ExecutionPlan:
        if self.llm is None:
            self.runtime.init_llm()

        skill_menu = SkillRegistry.get_selection_context()
        workflow_menu = self._get_workflow_menu()

        system = _PLANNER_SYSTEM_PROMPT.format(
            skill_menu=skill_menu,
            workflow_menu=workflow_menu,
        )

        structured_llm = self.llm.with_structured_output(ExecutionPlan)

        try:
            plan: ExecutionPlan = await structured_llm.ainvoke(
                [
                    SystemMessage(content=system),
                    HumanMessage(content=f"User request: {task}"),
                ]
            )
        except Exception as exc:
            logger.warning("LLM planning failed: %s, falling back to chat", exc)
            return ExecutionPlan(
                goal="",
                intent="chat",
                complexity="simple",
                skills=[],
                workflow=None,
                steps=[],
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
    # 执行路径 1: Workflow — Graph.run() 引擎
    # ==================================================================

    _WORKFLOW_STATE_MAP: dict[str, Any] = {}  # 延迟导入避免循环依赖

    async def _execute_via_workflow(self, plan: ExecutionPlan, task: str) -> str:
        """通过 WorkflowGraph 执行多步工作流。

        1. 从 WorkflowRegistry 获取对应 Graph
        2. 构建 WorkflowState（按 workflow 类型选择正确的 State 子类）
        3. 注入 Runtime 引用到 state
        4. graph.run(state, runtime) → 返回最终输出
        """
        wf_name = plan.workflow
        if not wf_name or self._workflow_registry is None:
            return await self.runtime.run(task, use_memory=True)

        try:
            graph = self._workflow_registry.build(wf_name)
        except Exception as exc:
            logger.error("构建工作流 '%s' 失败: %s", wf_name, exc)
            return f"[错误] 工作流 '{wf_name}' 构建失败: {exc}"

        # 按工作流名选择对应的 State 类型
        state = self._make_state(wf_name, task)

        # 注入 Runtime
        state._runtime = self.runtime
        state.session_id = self.runtime.state.session_id

        logger.info("执行工作流 '%s': %d 节点, task=%s", wf_name, len(graph._nodes), task[:60])

        try:
            result_state = await graph.run(state, runtime=self.runtime)
        except Exception as exc:
            logger.error("工作流 '%s' 执行失败: %s", wf_name, exc)
            return f"[错误] 工作流执行失败: {exc}"

        if result_state.status == "failed":
            logger.warning("工作流 '%s' 失败: %s", wf_name, result_state.errors)
            return "[工作流失败]\n" + "\n".join(result_state.errors)

        logger.info("工作流 '%s' 完成", wf_name)
        return result_state.final_output or "(工作流完成，无输出)"

    def _make_state(self, wf_name: str, task: str) -> Any:
        """按工作流类型构建对应的 WorkflowState 子类实例。"""
        if "dev" in wf_name:
            from haven.workflows.state import DevWorkflowState

            return DevWorkflowState(task=task, session_id=self.runtime.state.session_id)
        elif "research" in wf_name:
            from haven.workflows.state import ResearchWorkflowState

            return ResearchWorkflowState(task=task, session_id=self.runtime.state.session_id)
        elif "diagnosis" in wf_name:
            from haven.workflows.state import DiagnosisWorkflowState

            return DiagnosisWorkflowState(task=task, session_id=self.runtime.state.session_id)
        else:
            from haven.workflows.state import WorkflowState

            return WorkflowState(task=task, session_id=self.runtime.state.session_id)

    # ==================================================================
    # 执行路径 2: 自编排多步
    # ==================================================================

    async def _execute_steps(self, plan: ExecutionPlan, task: str) -> str:
        ordered = self._topological_sort(plan.steps)
        step_outputs: dict[int, str] = {}
        final = ""

        for step in ordered:
            skill_objs = self._load_skills([step.skill] if step.skill else [])

            # 前置步骤输出 → ContextManager 作为 tool_results 注入
            prev_results: dict[str, str] = {}
            for dep in step.depends_on:
                if dep in step_outputs:
                    prev_results[f"step_{dep}"] = step_outputs[dep]

            # 任务 prompt（不含前置输出，前置输出通过 ContextManager 注入 system prompt）
            step_task_parts = [f"原始任务: {task}", f"当前步骤: {step.description}"]
            if step.expected_output:
                step_task_parts.append(f"预期产出: {step.expected_output}")
            step_task = "\n".join(step_task_parts)

            result = await self.runtime.run(
                step_task,
                active_skills=skill_objs,
                use_memory=True,
                tool_results=prev_results or None,
            )
            step_outputs[step.order] = result
            final = result

        return final

    @staticmethod
    def _load_skills(names: list[str]) -> list[Any]:
        skills: list[Any] = []
        for name in names:
            try:
                skills.append(SkillRegistry.get(name))
            except KeyError:
                pass
        return skills

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
            for neighbor in adj.get(order, []):
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        return result
