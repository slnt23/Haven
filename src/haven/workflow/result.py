"""WorkflowResult —— Workflow 引擎统一输出协议。

Pipeline 和 Runtime 永远只读取 WorkflowResult.output。
Workflow 定义必须设置 state["final_output"]，这是唯一的输出契约。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class WorkflowResult:
    """WorkflowEngine 的统一输出。

    字段：
        output: 最终输出文本。来自 state["final_output"]。
        errors: 执行过程中的错误列表。
        raw_state: 完整的 LangGraph state dict（调试/审计用）。
    """

    output: str = ""
    errors: list[str] = field(default_factory=list)
    raw_state: dict[str, Any] = field(default_factory=dict)

    @property
    def success(self) -> bool:
        return len(self.errors) == 0 and bool(self.output)

    @classmethod
    def from_state(cls, state: dict[str, Any]) -> WorkflowResult:
        """从 LangGraph 执行后的 state dict 构造。"""
        output = state.get("final_output", "")
        errors = list(state.get("errors", []))
        if state.get("status") == "failed" and not errors:
            errors.append("工作流执行失败")
        return cls(output=output, errors=errors, raw_state=state)
