"""Haven V3 Runtime — Coordinator + 多专业 Agent + 工作流引擎。

Coordinator — 任务规划 + 多 Agent 调度
BaseAgent — 专业 Agent 基类 (Coder/Researcher/Diagnosis/General)
ContextBuilder — 统一上下文构建 (替代 Middleware 管道)
create_coordinator — 系统装配入口
"""

from haven.runtime.agents.base import BaseAgent
from haven.runtime.context import ContextBuilder
from haven.runtime.coordinator import Coordinator, ExecutionPlan, PlanStep
from haven.runtime.factory import create_coordinator
from haven.runtime.graphs import create_checkpointer
from haven.runtime.registry import WorkflowRegistry
from haven.runtime.state import AgentState

# 兼容旧 API — PlannerAgent/AgentRuntime 已删除，迁移到 Coordinator/BaseAgent

__all__ = [
    "Coordinator",
    "ExecutionPlan",
    "PlanStep",
    "BaseAgent",
    "ContextBuilder",
    "create_coordinator",
    "AgentState",
    "WorkflowRegistry",
    "create_checkpointer",
]
