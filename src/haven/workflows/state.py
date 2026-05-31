"""Workflow 状态容器。

各领域工作流继承 ``WorkflowState``，添加领域特定字段。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from langchain_core.messages import BaseMessage


@dataclass
class WorkflowState:
    """所有工作流的基类状态。在节点间流动并持久化。

    子类添加领域字段。不可序列化的字段以 ``_`` 前缀标记。
    """

    # -- 任务标识 --
    task: str = ""
    session_id: str = "default"

    # -- 消息历史 --
    messages: list[BaseMessage] = field(default_factory=list)

    # -- 执行控制 --
    current_node: str = ""
    node_outputs: dict[str, str] = field(default_factory=dict)
    node_retry_counts: dict[str, int] = field(default_factory=dict)
    max_retries_per_node: int = 3

    # -- 执行结果 --
    status: str = "pending"             # pending | running | completed | failed
    final_output: str = ""
    errors: list[str] = field(default_factory=list)

    # -- 时间 --
    started_at: float = 0.0

    # -- 运行时引用（不可序列化） --
    _runtime: Any = field(default=None, repr=False)


@dataclass
class DevWorkflowState(WorkflowState):
    """软件开发工作流专用状态。"""

    architecture_doc: str = ""
    source_code: str = ""
    code_language: str = "python"
    review_feedback: str = ""
    review_score: float = 0.0
    review_blockers: list[str] = field(default_factory=list)
    test_report: str = ""
    test_passed: bool = False
    test_failures: list[str] = field(default_factory=list)


@dataclass
class ResearchWorkflowState(WorkflowState):
    """调研工作流专用状态。"""

    research_topic: str = ""
    raw_findings: list[str] = field(default_factory=list)
    analyzed_insights: str = ""
    final_report: str = ""
    sources: list[str] = field(default_factory=list)


@dataclass
class DiagnosisWorkflowState(WorkflowState):
    """诊断工作流专用状态。"""

    symptoms: str = ""
    collected_info: str = ""
    possible_causes: str = ""
    diagnosis: str = ""
    recommendations: str = ""
