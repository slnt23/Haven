"""Haven Runtime —— Agent 运行时调度中心（Execution Layer）。

职责：
  - 请求入口       — Runtime.execute(task)
  - 任务规划       — Coordinator.plan() → ExecutionPlan
  - 执行调度       — Dispatcher.dispatch() → Workflow / Agent
  - 上下文构建     — ContextBuilder → system_prompt
  - Agent 执行     — BaseAgent → create_agent() → LLM

不负责：
  - Tool 解析/选择  — 全部交给 LangChain + LLM Function Calling
  - Skill→Tool 映射 — 已删除，Skill 仅影响 system_prompt

依赖方向（单向）：
  Config → Core → Tools → Runtime
"""

from haven.runtime.agents.base import BaseAgent
from haven.runtime.context import ContextBuilder
from haven.runtime.coordinator import Coordinator, ExecutionPlan, PlanStep
from haven.runtime.dispatcher import Dispatcher
from haven.runtime.factory import Runtime, create_runtime
from haven.runtime.stream import StreamChunk
from haven.runtime.registry import WorkflowRegistry
from haven.runtime.state import AgentState
from haven.runtime.workflows import create_checkpointer

__all__ = [
    "Runtime",
    "create_runtime",
    "Coordinator",
    "Dispatcher",
    "ExecutionPlan",
    "PlanStep",
    "BaseAgent",
    "ContextBuilder",
    "AgentState",
    "WorkflowRegistry",
    "create_checkpointer",
    "StreamChunk",
]
