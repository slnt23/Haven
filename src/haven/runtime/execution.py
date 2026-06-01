"""ExecutionState — 单次任务执行的运行状态。

职责边界：
  - RuntimeState  = 会话级（session identity + turn config + scratchpad）
  - ExecutionState = 任务级（task progress + step tracking + retry + timing）
  - WorkflowState  = 领域级（domain data + messages + 领域字段）

ExecutionState 是 WorkflowGraph、Checkpoint、Resume 的统一执行追踪载体。
PlannerAgent 不直接操作它——由 WorkflowGraph 和 AgentRuntime 维护。
"""

from __future__ import annotations

from dataclasses import dataclass, field
import time
import uuid


def _new_task_id() -> str:
    return uuid.uuid4().hex[:12]


def _now() -> float:
    return time.time()


@dataclass
class ExecutionState:
    """单次任务执行的完整运行时状态。

    创建时机：任务启动时由 WorkflowGraph 或 AgentRuntime 创建。
    生命周期：pending → running → completed / failed / paused

    用法::

        es = ExecutionState(task_id="abc", goal="写一个排序算法")
        es.start()

        es.complete_step("coder", output="def sort(arr): ...")
        es.fail_step("review", error="代码风格不符合 PEP8")
        es.retry_count += 1  # 手动重试

        if es.is_terminal:
            print(es.final_output)
    """

    # -- 任务标识 --
    task_id: str = field(default_factory=_new_task_id)
    goal: str = ""

    # -- 步骤追踪 --
    current_step: str = ""  # 当前执行的步骤/节点名
    completed_steps: list[str] = field(default_factory=list)
    failed_steps: list[str] = field(default_factory=list)
    step_outputs: dict[str, str] = field(default_factory=dict)

    # -- 重试 --
    retry_count: int = 0
    max_retries: int = 3
    node_retry_counts: dict[str, int] = field(default_factory=dict)

    # -- 状态 --
    status: str = "pending"  # pending | running | completed | failed | paused

    # -- 结果 --
    final_output: str = ""
    errors: list[str] = field(default_factory=list)

    # -- 时间 --
    created_at: float = field(default_factory=_now)
    updated_at: float = field(default_factory=_now)

    # -- 运行时引用（不可序列化） --
    _runtime: object = field(default=None, repr=False)

    # ==================================================================
    # 属性
    # ==================================================================

    @property
    def is_terminal(self) -> bool:
        return self.status in ("completed", "failed")

    @property
    def is_running(self) -> bool:
        return self.status == "running"

    @property
    def total_steps(self) -> int:
        return len(self.completed_steps) + len(self.failed_steps) + (1 if self.current_step else 0)

    @property
    def has_errors(self) -> bool:
        return len(self.errors) > 0

    # ==================================================================
    # 生命周期
    # ==================================================================

    def start(self) -> None:
        self.status = "running"
        self.created_at = _now()
        self.updated_at = self.created_at

    def complete_step(self, name: str, output: str = "") -> None:
        """标记一个步骤完成。"""
        if name and name not in self.completed_steps:
            self.completed_steps.append(name)
        if output:
            self.step_outputs[name] = output
        self.current_step = ""
        self._touch()

    def fail_step(self, name: str, error: str = "") -> None:
        """标记一个步骤失败。"""
        if name and name not in self.failed_steps:
            self.failed_steps.append(name)
        if error:
            self.errors.append(error)
        self._touch()

    def finish(self, output: str = "") -> None:
        """正常完成。"""
        self.status = "completed"
        if output:
            self.final_output = output
        self._touch()

    def fail(self, error: str = "") -> None:
        """标记任务失败。"""
        self.status = "failed"
        if error:
            self.errors.append(error)
        self._touch()

    def pause(self) -> None:
        """暂停执行（用于外部中断）。"""
        self.status = "paused"
        self._touch()

    def resume(self) -> None:
        """从暂停恢复。"""
        self.status = "running"
        self._touch()

    def _touch(self) -> None:
        self.updated_at = _now()

    # ==================================================================
    # 序列化
    # ==================================================================

    def snapshot(self) -> dict:
        """返回可序列化的快照（排除 _runtime 等不可序列化字段）。"""
        return {
            "task_id": self.task_id,
            "goal": self.goal,
            "current_step": self.current_step,
            "completed_steps": list(self.completed_steps),
            "failed_steps": list(self.failed_steps),
            "step_outputs": dict(self.step_outputs),
            "retry_count": self.retry_count,
            "max_retries": self.max_retries,
            "node_retry_counts": dict(self.node_retry_counts),
            "status": self.status,
            "final_output": self.final_output,
            "errors": list(self.errors),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_snapshot(cls, data: dict) -> "ExecutionState":
        """从快照恢复（Checkpoint resume）。"""
        return cls(
            task_id=data.get("task_id", ""),
            goal=data.get("goal", ""),
            current_step=data.get("current_step", ""),
            completed_steps=data.get("completed_steps", []),
            failed_steps=data.get("failed_steps", []),
            step_outputs=data.get("step_outputs", {}),
            retry_count=data.get("retry_count", 0),
            max_retries=data.get("max_retries", 3),
            node_retry_counts=data.get("node_retry_counts", {}),
            status=data.get("status", "pending"),
            final_output=data.get("final_output", ""),
            errors=data.get("errors", []),
            created_at=data.get("created_at", 0.0),
            updated_at=data.get("updated_at", 0.0),
        )


@dataclass
class ExecutionContext:
    """单次任务执行的取消控制。

    注入到 AgentRuntime 和 WorkflowGraph，在关键检查点读取 ``cancelled`` 标志。

    用法::

        ctx = ExecutionContext(task_id="abc")
        runtime.set_context(ctx)

        # 外部取消
        ctx.cancel()

        # Runtime / Workflow 内部每轮检查
        if ctx.cancelled:
            es.status = "cancelled"
            return
    """

    task_id: str = field(default_factory=_new_task_id)
    cancelled: bool = False
    started_at: float = field(default_factory=_now)

    def cancel(self) -> None:
        """标记为已取消。幂等——重复调用无副作用。"""
        self.cancelled = True
