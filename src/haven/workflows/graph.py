"""WorkflowGraph — DAG 执行引擎。

LangGraph 风格的最小实现:
  - add_node() / add_edge() / add_conditional_edge()
  - run(state, runtime) → state
  - Checkpointer 集成

用法::

    graph = WorkflowGraph(DevWorkflowState)
    graph.add_node("planner", PlannerNode())
    graph.add_node("coder", CoderNode())
    graph.add_edge("planner", "coder")
    graph.add_conditional_edge("coder", review_router)
    graph.set_entry_point("planner")

    state = DevWorkflowState(task="写一个排序算法")
    result = await graph.run(state, runtime=rt)
"""

from __future__ import annotations

import logging
import time
from typing import Any

from haven.workflows.state import WorkflowState
from haven.workflows.edges import Edge, ConditionalEdge
from haven.workflows.checkpoint import Checkpointer

logger = logging.getLogger("haven.workflow.graph")


class WorkflowGraph:
    """DAG 工作流执行引擎。

    支持:
      - 无条件边 + 条件边（Router 函数）
      - 重试（RETRY sentinel）
      - Checkpoint（每节点后自动保存）
      - 防死循环（max_iterations）
    """

    END = "__END__"

    def __init__(self, state_cls: type[WorkflowState]):
        self._state_cls = state_cls
        self._nodes: dict[str, Any] = {}
        self._edges: dict[str, Edge | ConditionalEdge] = {}
        self._entry_point: str = ""
        self._checkpointer: Checkpointer | None = None
        self._max_iterations: int = 20

    # ==================================================================
    # 图构建 API
    # ==================================================================

    def add_node(self, name: str, node: Any) -> "WorkflowGraph":
        self._nodes[name] = node
        return self

    def add_edge(self, source: str, target: str) -> "WorkflowGraph":
        if source in self._edges:
            raise ValueError(
                f"节点 '{source}' 已有一条出边。"
                f"使用 add_conditional_edge 代替。"
            )
        self._edges[source] = Edge(source, target)
        return self

    def add_conditional_edge(
        self, source: str, router, route_map: dict[str, str] | None = None,
    ) -> "WorkflowGraph":
        if source in self._edges:
            raise ValueError(f"节点 '{source}' 已有一条出边。")
        self._edges[source] = ConditionalEdge(source, router, route_map)
        return self

    def set_entry_point(self, name: str) -> "WorkflowGraph":
        if name not in self._nodes:
            raise ValueError(f"入口节点 '{name}' 未注册")
        self._entry_point = name
        return self

    def set_checkpointer(self, cp: Checkpointer) -> "WorkflowGraph":
        self._checkpointer = cp
        return self

    # ==================================================================
    # 执行
    # ==================================================================

    async def run(
        self,
        state: WorkflowState,
        *,
        runtime: Any = None,
        resume_from: str | None = None,
    ) -> WorkflowState:
        """执行工作流图。

        Args:
            state: 初始状态（或从 checkpoint 恢复的状态）。
            runtime: AgentRuntime 实例。每个 node 通过 state._runtime 访问。
            resume_from: checkpoint session_id，用于恢复中断的执行。

        Returns:
            执行完成后的最终状态。
        """
        # 恢复 checkpoint
        if resume_from and self._checkpointer:
            saved = await self._checkpointer.load(resume_from)
            if saved:
                state = saved
                logger.info("从 checkpoint 恢复: %s → %s", resume_from, getattr(state, "current_node", "?"))

        # 注入运行时
        if runtime is not None:
            state._runtime = runtime

        state.status = "running"
        state.started_at = time.time()

        current = resume_from or self._entry_point
        iteration = 0

        while iteration < self._max_iterations:
            iteration += 1

            # 终止
            if current == self.END:
                state.status = "completed"
                state.final_output = self._final_output(state)
                break

            # 查找节点
            node = self._nodes.get(current)
            if node is None:
                state.errors.append(f"节点 '{current}' 未注册")
                state.status = "failed"
                break

            # 执行节点
            state.current_node = current
            logger.info("Workflow[%d]: %s", iteration, current)

            try:
                updates = await node(state)
            except Exception as exc:
                logger.error("节点 '%s' 异常: %s", current, exc)
                updates = {
                    "errors": [*state.errors, f"[{current}] {exc}"],
                    "status": "failed",
                }

            self._apply_updates(state, updates)

            if state.status == "failed":
                break

            # 更新重试计数
            prev = state.node_retry_counts.get(current, 0)
            state.node_retry_counts[current] = prev + 1

            # Checkpoint
            if self._checkpointer:
                await self._checkpointer.save(state.session_id, current, state)

            # 确定下一个节点
            edge = self._edges.get(current)
            if edge is None:
                state.status = "completed"
                state.final_output = self._final_output(state)
                break
            elif isinstance(edge, ConditionalEdge):
                next_node = await edge.resolve(state)
            else:
                next_node = edge.target

            # RETRY
            if next_node == ConditionalEdge.RETRY:
                retries = state.node_retry_counts.get(current, 0)
                if retries < state.max_retries_per_node:
                    next_node = current
                    logger.info("重试节点 '%s' (%d/%d)", current, retries + 1, state.max_retries_per_node)
                else:
                    state.status = "failed"
                    state.errors.append(
                        f"节点 '{current}' 超过最大重试次数 {state.max_retries_per_node}"
                    )
                    break

            current = next_node

        # 最终 checkpoint
        if self._checkpointer and state.status in ("completed", "failed"):
            await self._checkpointer.save(state.session_id, self.END, state)

        return state

    # ==================================================================
    # 内部
    # ==================================================================

    @staticmethod
    def _apply_updates(state: WorkflowState, updates: dict) -> None:
        for key, value in updates.items():
            if hasattr(state, key):
                current_val = getattr(state, key)
                if isinstance(current_val, dict) and isinstance(value, dict):
                    current_val.update(value)
                elif isinstance(current_val, list) and isinstance(value, list):
                    current_val.extend(value)
                else:
                    setattr(state, key, value)

    @staticmethod
    def _final_output(state: WorkflowState) -> str:
        if state.status == "failed":
            return "\n".join(state.errors)
        outputs = state.node_outputs
        if outputs:
            keys = list(outputs.keys())
            return outputs[keys[-1]]
        return ""
