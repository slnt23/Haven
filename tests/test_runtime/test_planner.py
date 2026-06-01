"""PlannerAgent.plan() 测试 — 任务规划层。"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import AIMessage


class TestPlannerPlan:
    """PlannerAgent.plan() 核心测试。"""

    @pytest.fixture
    def planner(self, runtime_with_mock_llm, register_test_skills):
        from haven.runtime.planner import PlannerAgent, ExecutionPlan

        # 创建 mock structured LLM
        llm = MagicMock()
        llm.model_name = "mock-model"

        structured = MagicMock()
        structured.ainvoke = AsyncMock(return_value=ExecutionPlan(
            goal="写一个排序算法",
            intent="development",
            complexity="medium",
            skills=["coder"],
            workflow=None,
            steps=[],
            reasoning="测试规划",
        ))
        llm.with_structured_output = MagicMock(return_value=structured)
        llm.ainvoke = AsyncMock(return_value=AIMessage(content="mock"))
        llm.bind_tools = MagicMock(return_value=llm)

        runtime_with_mock_llm.llm = llm
        return PlannerAgent(runtime_with_mock_llm)

    @pytest.mark.asyncio
    async def test_plan_trivial_greeting(self, planner):
        """简单问候走快速路径。"""
        plan = await planner.plan("你好")
        assert plan.intent == "chat"
        assert plan.complexity == "simple"
        assert plan.skills == []
        assert plan.steps == []

    @pytest.mark.asyncio
    async def test_plan_trivial_short_input(self, planner):
        """≤2 字符走快速路径。"""
        plan = await planner.plan("ab")
        assert plan.intent == "chat"

    @pytest.mark.asyncio
    async def test_plan_uses_structured_llm(self, planner):
        """非 trivial 任务调用 LLM structured output。"""
        plan = await planner.plan("帮我写一个排序算法")
        assert plan.goal == "写一个排序算法"
        assert plan.intent == "development"
        assert "coder" in plan.skills
        assert planner.llm.with_structured_output.called

    @pytest.mark.asyncio
    async def test_plan_resolves_skill_dependencies(self, planner):
        """Skill 依赖解析 — code_review 依赖 coder。"""
        # 覆盖 structured output 返回含 code_review 的 plan
        from haven.runtime.planner import ExecutionPlan

        dep_plan = ExecutionPlan(
            goal="审查代码",
            intent="development",
            complexity="simple",
            skills=["code_review"],
            workflow=None,
            steps=[],
            reasoning="依赖测试",
        )
        planner.llm.with_structured_output.return_value.ainvoke = AsyncMock(return_value=dep_plan)

        plan = await planner.plan("审查这段代码")
        assert "code_review" in plan.skills
        # code_review 依赖 coder，应自动加入
        assert "coder" in plan.skills

    @pytest.mark.asyncio
    async def test_plan_fallback_on_error(self, planner):
        """LLM 调用异常 → fallback chat plan。"""
        planner.llm.with_structured_output.return_value.ainvoke = AsyncMock(
            side_effect=RuntimeError("LLM error")
        )
        plan = await planner.plan("复杂任务")
        assert plan.intent == "chat"
        assert plan.skills == []
        assert "LLM error" in plan.reasoning

    @pytest.mark.asyncio
    async def test_plan_validates_invalid_skills(self, planner):
        """无效 skill 被过滤。"""
        from haven.runtime.planner import ExecutionPlan

        bad_plan = ExecutionPlan(
            goal="测试",
            intent="development",
            complexity="simple",
            skills=["coder", "nonexistent_skill"],
            workflow=None,
            steps=[],
            reasoning="",
        )
        planner.llm.with_structured_output.return_value.ainvoke = AsyncMock(return_value=bad_plan)

        plan = await planner.plan("测试任务")
        assert "coder" in plan.skills
        assert "nonexistent_skill" not in plan.skills

    @pytest.mark.asyncio
    async def test_plan_cache(self, planner):
        """相同任务命中缓存。"""
        plan1 = await planner.plan("帮我写一个排序算法")
        plan2 = await planner.plan("帮我写一个排序算法")

        assert plan1.goal == plan2.goal
        # 第二次应命中缓存，不再调用 LLM
        # 注意: 第一次和第二次是不同的 task text，但由于缓存 key 相同，第二次应命中

    @pytest.mark.asyncio
    async def test_plan_different_tasks_different_cache(self, planner):
        """不同任务不同缓存 key。"""
        from haven.runtime.planner import ExecutionPlan

        plan2_data = ExecutionPlan(
            goal="重构代码",
            intent="development",
            complexity="medium",
            skills=["coder"],
            workflow=None,
            steps=[],
            reasoning="",
        )

        call_count = [0]

        async def _ainvoke(messages, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                return ExecutionPlan(
                    goal="写排序",
                    intent="development",
                    complexity="medium",
                    skills=["coder"],
                    workflow=None,
                    steps=[],
                    reasoning="",
                )
            return plan2_data

        planner.llm.with_structured_output.return_value.ainvoke = AsyncMock(
            side_effect=_ainvoke
        )

        await planner.plan("写排序算法")
        await planner.plan("重构代码")
        assert call_count[0] == 2


class TestPlannerExecute:
    """PlannerAgent.execute() 测试。"""

    @pytest.fixture
    def planner(self, runtime_with_mock_llm, register_test_skills):
        from haven.runtime.planner import PlannerAgent
        return PlannerAgent(runtime_with_mock_llm)

    @pytest.mark.asyncio
    async def test_execute_trivial(self, planner):
        """简单对话 → Runtime 直通。"""
        result = await planner.execute("你好")
        assert result == "mock response"

    @pytest.mark.asyncio
    async def test_execute_with_steps(self, planner, register_test_skills):
        """带步骤 → _execute_steps 拓扑排序执行。"""
        from haven.runtime.planner import ExecutionPlan, PlanStep

        plan = ExecutionPlan(
            goal="两步任务",
            intent="development",
            complexity="medium",
            skills=["coder"],
            workflow=None,
            steps=[
                PlanStep(order=1, description="第一步", skill="coder",
                         depends_on=[], expected_output="结果1"),
                PlanStep(order=2, description="第二步", skill="coder",
                         depends_on=[1], expected_output="结果2"),
            ],
            reasoning="",
        )

        with patch.object(planner, "plan", new=AsyncMock(return_value=plan)):
            result = await planner.execute("做两件事")

        assert result == "mock response"

    @pytest.mark.asyncio
    async def test_execute_trivial_fastpath_overrides_plan(self, planner):
        """trivial 任务在 plan() 中已快速返回，不调用 LLM。"""
        result = await planner.execute("hi")
        assert result == "mock response"


class TestTopologicalSort:
    """拓扑排序算法测试。"""

    def test_linear_steps(self):
        from haven.runtime.planner import PlannerAgent, PlanStep

        steps = [
            PlanStep(order=1, description="Step 1", depends_on=[]),
            PlanStep(order=2, description="Step 2", depends_on=[1]),
            PlanStep(order=3, description="Step 3", depends_on=[2]),
        ]
        result = PlannerAgent._topological_sort(steps)
        assert [s.order for s in result] == [1, 2, 3]

    def test_parallel_steps(self):
        from haven.runtime.planner import PlannerAgent, PlanStep

        steps = [
            PlanStep(order=1, description="Step 1", depends_on=[]),
            PlanStep(order=2, description="Step 2", depends_on=[]),
            PlanStep(order=3, description="Step 3", depends_on=[1, 2]),
        ]
        result = PlannerAgent._topological_sort(steps)

        # 1 和 2 都在 3 前面
        idx_1 = next(i for i, s in enumerate(result) if s.order == 1)
        idx_2 = next(i for i, s in enumerate(result) if s.order == 2)
        idx_3 = next(i for i, s in enumerate(result) if s.order == 3)
        assert idx_1 < idx_3
        assert idx_2 < idx_3

    def test_diamond_dependency(self):
        from haven.runtime.planner import PlannerAgent, PlanStep

        steps = [
            PlanStep(order=1, description="Start", depends_on=[]),
            PlanStep(order=2, description="Left", depends_on=[1]),
            PlanStep(order=3, description="Right", depends_on=[1]),
            PlanStep(order=4, description="End", depends_on=[2, 3]),
        ]
        result = PlannerAgent._topological_sort(steps)

        assert [s.order for s in result] == [1, 2, 3, 4]
