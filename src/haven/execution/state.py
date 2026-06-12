"""ExecutionState —— 执行过程的运行时状态。"""

from __future__ import annotations

from dataclasses import dataclass, field

from haven.execution.request import ExecutionPlan


@dataclass
class ExecutionState:
    """跟踪单次执行的生命周期。"""

    task: str = ""
    session_id: str = "default"
    trace_id: str = ""
    plan: ExecutionPlan | None = None
    current_step: str = ""
    completed_steps: list[str] = field(default_factory=list)
    status: str = "pending"  # pending → running → completed | failed
    errors: list[str] = field(default_factory=list)
