"""ExecutionRequest —— 执行请求的数据模型。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class PlanStep(BaseModel):
    """执行计划中的单个步骤。"""

    order: int = Field(description="步骤序号，从 1 开始")
    description: str = Field(description="步骤描述")
    skill: str | None = Field(default=None, description="此步骤需要的 skill 名")
    depends_on: list[int] = Field(default_factory=list, description="依赖的步骤序号")
    expected_output: str = Field(default="", description="预期产出描述")


class ExecutionPlan(BaseModel):
    """Planner 的规划输出 —— 由 LLM Structured Output 生成。"""

    goal: str = Field(default="", description="用户目标的一句话概括")
    intent: str = Field(default="", description="意图分类标签")
    agent_type: str = Field(
        default="general",
        description="调度到的 Agent 类型: coder | researcher | diagnosis | general",
    )
    complexity: str = Field(default="simple", description="simple | medium | complex")
    skills: list[str] = Field(default_factory=list, description="需要激活的 skill 名")
    workflow: str | None = Field(default=None, description="预定义工作流名")
    steps: list[PlanStep] = Field(default_factory=list, description="执行步骤")
    reasoning: str = Field(default="", description="规划理由")


class ExecutionRequest(BaseModel):
    """用户请求的标准化输入模型。

    由 Interface 层创建，传递给 Executor.execute()。
    """

    task: str = Field(description="用户输入文本")
    session_id: str = Field(default="default")
    options: dict = Field(default_factory=dict, description="执行选项")
    trace_id: str = Field(default="", description="追踪标识，为空时自动生成")
