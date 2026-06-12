"""ExecutionResponse —— 执行响应的数据模型。"""

from __future__ import annotations

from pydantic import BaseModel, Field

from haven.kernel.event import AgentEvent


class ExecutionResponse(BaseModel):
    """Executor 的统一响应模型。"""

    result: str = Field(default="", description="响应文本")
    events: list[AgentEvent] = Field(default_factory=list, description="执行过程中的事件")
    trace_id: str = Field(default="", description="追踪标识")
    plan_summary: str | None = Field(default=None, description="规划摘要")
    agent_type: str | None = Field(default=None)
    skills_used: list[str] = Field(default_factory=list)
    tools_called: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
