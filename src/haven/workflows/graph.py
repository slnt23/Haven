"""WorkflowGraph — DAG 执行引擎。

LangGraph 风格的最小实现:
  - add_node() / add_edge() / add_conditional_edge()
  - run(state, runtime) → state
  - Checkpointer 集成
  - V3: 执行追踪通过 state.execution (ExecutionState) 读写

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
from typing import Any

from haven.workflows.checkpoint import Checkpointer
from haven.workflows.edges import ConditionalEdge, Edge
from haven.workflows.state import WorkflowState

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
        self._exec_ctx: Any = None

    # ==================================================================
    # 图构建 API
    # ==================================================================

    def add_node(self, name: str, node: Any) -> "WorkflowGraph":
        self._nodes[name] = node
        return self

    def add_edge(self, source: str, target: str) -> "WorkflowGraph":
        if source in self._edges:
            raise ValueError(f"节点 '{source}' 已有一条出边。使用 add_conditional_edge 代替。")
        self._edges[source] = Edge(source, target)
        return self

    def add_conditional_edge(
        self,
        source: str,
        router,
        route_map: dict[str, str] | None = None,
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

    def set_context(self, ctx: Any) -> "WorkflowGraph":
        """注入 ExecutionContext 以支持外部取消。"""
        self._exec_ctx = ctx
        return self

    @property
    def cancelled(self) -> bool:
        if self._exec_ctx is None:
            return False
        return self._exec_ctx.cancelled

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

        V3: 所有执行追踪通过 state.execution (ExecutionState) 读写。

        Args:
            state: 初始状态（或从 checkpoint 恢复的状态）。
            runtime: AgentRuntime 实例。每个 node 通过 state._runtime 访问。
            resume_from: checkpoint session_id，用于恢复中断的执行。

        Returns:
            执行完成后的最终状态。
        """
        es = state.execution

        # 恢复 checkpoint
        if resume_from and self._checkpointer:
            saved = await self._checkpointer.load(resume_from)
            if saved:
                # 从 ExecutionState 快照恢复执行位置
                if saved.get("execution") is not None:
                    state.execution = saved["execution"]
                    es = state.execution
                    logger.info("从 checkpoint 恢复: %s → %s", resume_from, es.current_step)

        # 注入运行时
        if runtime is not None:
            state._runtime = runtime
            es._runtime = runtime
            # 传递取消上下文
            if self._exec_ctx is not None and hasattr(runtime, "set_context"):
                runtime.set_context(self._exec_ctx)

        # 启动执行追踪（若未恢复则新建计时）
        if es.status != "paused":
            es.start()

        current = (
            es.current_step if es.current_step and resume_from else resume_from or self._entry_point
        )
        iteration = 0

        while iteration < self._max_iterations:
            iteration += 1

            # 取消检查
            if self.cancelled:
                logger.info("Workflow cancelled at node '%s'", current)
                es.status = "cancelled"
                es._touch()
                break

            # 终止
            if current == self.END:
                es.finish(self._final_output(state))
                break

            # 查找节点
            node = self._nodes.get(current)
            if node is None:
                es.fail(f"节点 '{current}' 未注册")
                break

            # 执行节点
            es.current_step = current
            logger.info("Workflow[%d]: %s", iteration, current)

            try:
                updates = await node(state)
            except Exception as exc:
                logger.error("节点 '%s' 异常: %s", current, exc)
                updates = {
                    "errors": [f"[{current}] {exc}"],
                    "status": "failed",
                }

            self._apply_updates(state, updates)

            if es.status == "failed":
                break

            # 更新重试计数
            prev = es.node_retry_counts.get(current, 0)
            es.node_retry_counts[current] = prev + 1

            # Checkpoint — 从 ExecutionState 持久化
            if self._checkpointer:
                await self._checkpointer.save(state.session_id, current, state)

            # 确定下一个节点
            edge = self._edges.get(current)
            if edge is None:
                es.finish(self._final_output(state))
                break
            elif isinstance(edge, ConditionalEdge):
                next_node = await edge.resolve(state)
            else:
                next_node = edge.target

            # RETRY
            if next_node == ConditionalEdge.RETRY:
                retries = es.node_retry_counts.get(current, 0)
                if retries < es.max_retries:
                    next_node = current
                    logger.info("重试节点 '%s' (%d/%d)", current, retries + 1, es.max_retries)
                else:
                    es.fail(f"节点 '{current}' 超过最大重试次数 {es.max_retries}")
                    break

            current = next_node

        # 最终 checkpoint
        if self._checkpointer and es.is_terminal:
            await self._checkpointer.save(state.session_id, self.END, state)

        return state

    # ==================================================================
    # 内部
    # ==================================================================

    # 需要同步到 ExecutionState 的键
    _EXECUTION_KEYS: dict[str, str] = {
        "current_node": "current_step",
        "node_outputs": "step_outputs",
        "node_retry_counts": "node_retry_counts",
        "status": "status",
        "errors": "errors",
        "final_output": "final_output",
    }

    @classmethod
    def _apply_updates(cls, state: WorkflowState, updates: dict) -> None:
        """将节点返回的 updates 合并到 state 和 state.execution。

        执行类字段（current_node / node_outputs / status / errors）
        同时写入 state.execution.*（权威）和 state.*（向后兼容）。

        领域字段（architecture_doc 等）仅写入 state.*。
        """
        es = state.execution

        for key, value in updates.items():
            # 写入 state（保持向后兼容）
            if hasattr(state, key):
                current_val = getattr(state, key)
                if isinstance(current_val, dict) and isinstance(value, dict):
                    current_val.update(value)
                elif isinstance(current_val, list) and isinstance(value, list):
                    current_val.extend(value)
                else:
                    setattr(state, key, value)

            # 同步到 ExecutionState
            if key in cls._EXECUTION_KEYS:
                es_key = cls._EXECUTION_KEYS[key]
                es_val = getattr(es, es_key, None)
                if isinstance(es_val, dict) and isinstance(value, dict):
                    es_val.update(value)
                elif isinstance(es_val, list) and isinstance(value, list):
                    es_val.extend(value)
                else:
                    setattr(es, es_key, value)

    @staticmethod
    def _final_output(state: WorkflowState) -> str:
        es = state.execution
        if es.status == "failed":
            return "\n".join(es.errors)
        outputs = es.step_outputs
        if outputs:
            keys = list(outputs.keys())
            return outputs[keys[-1]]
        return ""
