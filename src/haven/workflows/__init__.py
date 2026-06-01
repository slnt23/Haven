"""Haven Workflows — LangGraph StateGraph 工作流引擎。"""

from __future__ import annotations

from langgraph.constants import END

from .graph import create_checkpointer
from .registry import WorkflowRegistry
from .state import (
    AgentState,
    DevAgentState,
    DiagnosisAgentState,
    ResearchAgentState,
)

# 图定义在 graphs/ 目录中，需要时取消注释即可触发 WorkflowRegistry 自动注册
# from .graphs import dev as _dev  # noqa: F401
# from .graphs import diagnosis as _diagnosis  # noqa: F401
# from .graphs import research as _research  # noqa: F401

__all__ = [
    "AgentState",
    "DevAgentState",
    "ResearchAgentState",
    "DiagnosisAgentState",
    "END",
    "WorkflowRegistry",
    "create_checkpointer",
]
