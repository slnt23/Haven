"""Haven V3 Runtime — 执行引擎 + 规划层 + 工作流引擎。

AgentRuntime — 基于 LangGraph create_react_agent 的执行引擎
PlannerAgent — 任务规划（理解 + 拆解 + Skill选择 + Workflow匹配）
WorkflowRegistry — 工作流注册与发现
create_agent — 系统装配入口
"""

from haven.runtime.factory import create_agent
from haven.runtime.graphs import create_checkpointer
from haven.runtime.planner import ExecutionPlan, PlannerAgent, PlanStep
from haven.runtime.registry import WorkflowRegistry
from haven.runtime.runtime import AgentRuntime
from haven.runtime.state import AgentState

# 图定义在 graphs/ 目录中，需要时取消注释即可触发 WorkflowRegistry 自动注册
# from haven.runtime.graphs import dev as _dev  # noqa: F401
# from haven.runtime.graphs import diagnosis as _diagnosis  # noqa: F401
# from haven.runtime.graphs import research as _research  # noqa: F401

__all__ = [
    "AgentRuntime",
    "PlannerAgent",
    "ExecutionPlan",
    "PlanStep",
    "create_agent",
    "AgentState",
    "WorkflowRegistry",
    "create_checkpointer",
]
