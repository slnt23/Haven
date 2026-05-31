"""Edge 类型定义 + 内置 Router 函数。

- Edge: 无条件边 (A → B)
- ConditionalEdge: 条件边 (A → Router(state) → B/C/D...)
"""

from __future__ import annotations

from typing import Any, Callable, Awaitable

from haven.workflows.state import WorkflowState, DevWorkflowState

# Router 函数签名
RouterFunc = Callable[[WorkflowState], str | Awaitable[str]]


class Edge:
    """无条件边。source 完成后总是到 target。"""

    def __init__(self, source: str, target: str):
        self.source = source
        self.target = target

    def __repr__(self) -> str:
        return f"{self.source} → {self.target}"


class ConditionalEdge:
    """条件边。根据 Router 函数动态决定下一步。

    Router 返回:
      - 节点名 → 跳到该节点
      - ConditionalEdge.END → 工作流结束
      - ConditionalEdge.RETRY → 重试当前节点
    """

    END = "__END__"
    RETRY = "__RETRY__"

    def __init__(
        self,
        source: str,
        router: RouterFunc,
        route_map: dict[str, str] | None = None,
    ):
        self.source = source
        self.router = router
        self.route_map = route_map or {}

    async def resolve(self, state: WorkflowState) -> str:
        result = self.router(state)
        if hasattr(result, "__await__"):
            result = await result
        return self.route_map.get(result, result)

    def __repr__(self) -> str:
        return f"{self.source} → [router]"


# ====================================================================
# 内置 Router 函数
# ====================================================================


def test_router(state: WorkflowState) -> str:
    """测试路由：通过 → END；失败 → coder（如未超限）。"""
    dev_state = state  # type: DevWorkflowState
    retries = dev_state.node_retry_counts.get("coder", 0)

    if dev_state.test_passed:
        return ConditionalEdge.END

    if retries >= dev_state.max_retries_per_node:
        return ConditionalEdge.END
    return "coder"


def research_quality_router(state: WorkflowState) -> str:
    """调研质量路由：有知识缺口 + 未超限 → searcher；否则 → synthesizer。"""
    rs = state  # type: Any  # ResearchWorkflowState
    search_count = state.node_retry_counts.get("searcher", 0)

    if (
        hasattr(rs, "analyzed_insights")
        and "知识缺口" in rs.analyzed_insights
        and search_count < 3
    ):
        return "searcher"
    return "synthesizer"
