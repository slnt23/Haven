"""调研工作流。

Graph: searcher → analyst ─┬→ synthesizer → END
                   ▲        │
                   │ 缺口   │
                   └────────┘ (retry ≤ 3)
"""

from haven.workflows.checkpoint import SQLiteCheckpointer
from haven.workflows.edges import research_quality_router
from haven.workflows.graph import WorkflowGraph
from haven.workflows.nodes import AnalystNode, SearcherNode, SynthesizerNode
from haven.workflows.registry import WorkflowRegistry
from haven.workflows.state import ResearchWorkflowState


def create_research_workflow() -> WorkflowGraph:
    """创建调研工作流。

    ┌──────────┐   ┌─────────┐   ┌─────────────┐
    │ searcher │ → │ analyst │ → │ synthesizer │ → END
    └──────────┘   └────┬────┘   └─────────────┘
                    ▲    │
                    │    │ quality check → 缺口
                    └────┘
    """
    graph = WorkflowGraph(ResearchWorkflowState)

    graph.add_node("searcher", SearcherNode())
    graph.add_node("analyst", AnalystNode())
    graph.add_node("synthesizer", SynthesizerNode())

    graph.add_edge("searcher", "analyst")
    graph.add_conditional_edge("analyst", research_quality_router)

    graph.set_entry_point("searcher")
    graph.set_checkpointer(SQLiteCheckpointer())

    return graph


create_research_workflow.description = (
    "调研工作流。信息搜集 → 分析 → 报告生成。存在知识缺口时自动补充搜索。"
)
create_research_workflow.use_cases = "技术调研、竞品分析、文献综述、市场研究"
create_research_workflow.step_count = 3

WorkflowRegistry.register("research_flow")(create_research_workflow)
