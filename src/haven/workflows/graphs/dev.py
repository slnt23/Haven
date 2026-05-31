"""软件开发工作流。

Graph: planner → architect → coder → reviewer → tester
                                     ▲              │
                                     │    fail      │
                                     └──────────────┘ (retry ≤ 3)
"""

from haven.workflows.graph import WorkflowGraph
from haven.workflows.state import DevWorkflowState
from haven.workflows.nodes import (
    PlannerNode, ArchitectNode, CoderNode, ReviewerNode, TesterNode,
)
from haven.workflows.edges import test_router
from haven.workflows.checkpoint import SQLiteCheckpointer
from haven.workflows.registry import WorkflowRegistry


def create_dev_workflow() -> WorkflowGraph:
    """创建软件开发工作流。

    ┌──────────┐   ┌───────────┐   ┌───────┐   ┌──────────┐   ┌────────┐
    │ planner  │ → │ architect │ → │ coder │ → │ reviewer │ → │ tester │
    └──────────┘   └───────────┘   └───────┘   └──────────┘   └───┬────┘
                                       ▲                          │
                                       │         fail (≤3)       │
                                       └──────────────────────────┘
    """
    graph = WorkflowGraph(DevWorkflowState)

    graph.add_node("planner", PlannerNode())
    graph.add_node("architect", ArchitectNode())
    graph.add_node("coder", CoderNode())
    graph.add_node("reviewer", ReviewerNode())
    graph.add_node("tester", TesterNode())

    graph.add_edge("planner", "architect")
    graph.add_edge("architect", "coder")
    graph.add_edge("coder", "reviewer")
    graph.add_edge("reviewer", "tester")

    graph.add_conditional_edge("tester", test_router)

    graph.set_entry_point("planner")
    graph.set_checkpointer(SQLiteCheckpointer())

    return graph


# Set metadata for WorkflowRegistry
create_dev_workflow.description = "软件开发工作流。需求分析 → 架构设计 → 编码 → 审查 → 测试。支持失败重试（最多3次）。"
create_dev_workflow.use_cases = "代码生成、Bug修复、架构设计、功能开发"
create_dev_workflow.step_count = 5

WorkflowRegistry.register("dev_flow")(create_dev_workflow)
