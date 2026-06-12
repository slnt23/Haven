"""Workflow 状态定义 —— LangGraph TypedDict 兼容。"""

from __future__ import annotations

from operator import add
from typing import Annotated, Any, TypedDict

from langchain_core.messages import BaseMessage


def _merge_dict(a: dict, b: dict) -> dict:
    return {**a, **b}


class AgentState(TypedDict, total=False):
    """所有工作流的基础状态。"""

    task: str
    session_id: str

    messages: Annotated[list[BaseMessage], add]
    errors: Annotated[list[str], add]
    completed_steps: Annotated[list[str], add]

    current_step: str
    node_outputs: Annotated[dict[str, str], _merge_dict]
    node_retry_counts: Annotated[dict[str, int], _merge_dict]
    max_retries_per_node: int

    plan_skills: list[str]

    status: str
    final_output: str
    started_at: float
