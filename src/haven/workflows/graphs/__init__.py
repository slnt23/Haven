"""预定义工作流图。"""

from haven.workflows.graphs.dev import _create_dev_workflow as create_dev_workflow
from haven.workflows.graphs.diagnosis import _create_diagnosis_workflow as create_diagnosis_workflow
from haven.workflows.graphs.research import _create_research_workflow as create_research_workflow

__all__ = [
    "create_dev_workflow",
    "create_research_workflow",
    "create_diagnosis_workflow",
]
