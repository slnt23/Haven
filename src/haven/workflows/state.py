"""Workflow 状态定义 — LangGraph TypedDict 兼容。

各领域工作流继承基础 State，通过 Annotated reducer 控制字段合并策略。
"""

from __future__ import annotations

from operator import add
from typing import Annotated, Any, TypedDict

from langchain_core.messages import BaseMessage


class AgentState(TypedDict, total=False):
    """所有工作流的基础状态。

    字段合并规则：
      - Annotated[list, add]: 追加合并
      - 无 Annotated: 覆盖
    """

    task: str
    session_id: str

    messages: Annotated[list[BaseMessage], add]
    errors: Annotated[list[str], add]
    completed_steps: Annotated[list[str], add]

    current_step: str
    node_outputs: Annotated[dict[str, str], _merge_dict]  # noqa: F821
    node_retry_counts: Annotated[dict[str, int], _merge_dict]  # noqa: F821
    max_retries_per_node: int

    status: str
    final_output: str

    started_at: float


class DevAgentState(AgentState, total=False):
    """软件开发工作流状态。"""

    architecture_doc: str
    source_code: str
    code_language: str
    review_feedback: str
    review_score: float
    review_blockers: Annotated[list[str], add]
    test_report: str
    test_passed: bool
    test_failures: Annotated[list[str], add]


class ResearchAgentState(AgentState, total=False):
    """调研工作流状态。"""

    research_topic: str
    raw_findings: Annotated[list[str], add]
    analyzed_insights: str
    final_report: str
    sources: Annotated[list[str], add]


class DiagnosisAgentState(AgentState, total=False):
    """诊断工作流状态。"""

    symptoms: str
    collected_info: str
    possible_causes: str
    diagnosis: str
    recommendations: str


def _merge_dict(a: dict, b: dict) -> dict:
    return {**a, **b}
