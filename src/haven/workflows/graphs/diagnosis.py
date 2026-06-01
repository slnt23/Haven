"""诊断工作流。

Graph: collector → analyzer → adviser → END

适合医疗症状分析和分诊建议。
"""

from haven.workflows.checkpoint import SQLiteCheckpointer
from haven.workflows.graph import WorkflowGraph
from haven.workflows.nodes import AdviserNode, AnalyzerNode, CollectorNode
from haven.workflows.registry import WorkflowRegistry
from haven.workflows.state import DiagnosisWorkflowState


def create_diagnosis_workflow() -> WorkflowGraph:
    """创建诊断工作流。

    ┌───────────┐   ┌──────────┐   ┌─────────┐
    │ collector │ → │ analyzer │ → │ adviser │ → END
    └───────────┘   └──────────┘   └─────────┘
    """
    graph = WorkflowGraph(DiagnosisWorkflowState)

    graph.add_node("collector", CollectorNode())
    graph.add_node("analyzer", AnalyzerNode())
    graph.add_node("adviser", AdviserNode())

    graph.add_edge("collector", "analyzer")
    graph.add_edge("analyzer", "adviser")

    graph.set_entry_point("collector")
    graph.set_checkpointer(SQLiteCheckpointer())

    return graph


create_diagnosis_workflow.description = (
    "诊断工作流。信息收集 → 症状分析 → 分级建议。适用于医疗健康场景。"
)
create_diagnosis_workflow.use_cases = "症状分析、健康咨询、分诊建议"
create_diagnosis_workflow.step_count = 3

WorkflowRegistry.register("diagnosis_flow")(create_diagnosis_workflow)
