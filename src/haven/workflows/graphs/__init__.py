"""预定义工作流图。"""

from haven.workflows.graphs.dev import create_dev_workflow
from haven.workflows.graphs.research import create_research_workflow
from haven.workflows.graphs.diagnosis import create_diagnosis_workflow

__all__ = [
    "create_dev_workflow",
    "create_research_workflow",
    "create_diagnosis_workflow",
]
