"""诊断工作流。

Graph: collector → analyzer → adviser → END
"""

from __future__ import annotations

from langgraph.constants import END
from langgraph.graph import StateGraph
from langchain_core.runnables import RunnableConfig

from haven.workflow.helpers import create_checkpointer
from haven.workflow.helpers import run_agent_node
from haven.workflow.registry import WorkflowRegistry
from haven.workflow.state import AgentState


class DiagnosisAgentState(AgentState, total=False):
    """诊断工作流状态。"""

    symptoms: str
    collected_info: str
    possible_causes: str
    diagnosis: str
    recommendations: str


async def _collector_node(state: DiagnosisAgentState, config: RunnableConfig) -> dict:
    task = state.get("task", "")
    prompt = f"""## 任务：信息收集

收集用户信息以辅助诊断。

用户描述: {task}

询问并收集: 持续时间、伴随症状、既往病史、用药情况。"""

    output = await run_agent_node(
        config, prompt, skill_tags=["medical"], state=state, agent_type="diagnosis", task=task,
    )
    return {
        "current_step": "collector",
        "completed_steps": ["collector"],
        "node_outputs": {"collector": output},
        "collected_info": output,
    }


async def _analyzer_node(state: DiagnosisAgentState, config: RunnableConfig) -> dict:
    task = state.get("task", "")
    prompt = f"""## 任务：症状分析

分析症状并给出可能的原因。

症状: {task}
已收集信息: {state.get("collected_info", "")}

输出:
1. 可能的病因列表（按可能性排序）
2. 每种可能性的置信度
3. 建议的下一步"""

    output = await run_agent_node(
        config, prompt, skill_tags=["medical"], state=state, agent_type="diagnosis", task=task,
    )
    return {
        "current_step": "analyzer",
        "completed_steps": ["analyzer"],
        "node_outputs": {"analyzer": output},
        "possible_causes": output,
    }


async def _adviser_node(state: DiagnosisAgentState, config: RunnableConfig) -> dict:
    task = state.get("task", "")
    prompt = f"""## 任务：给出建议

基于分析给出分级的医疗建议。

症状: {task}
分析结果: {state.get("possible_causes", "")}

输出:
1. 自我处理建议
2. 建议就医的情况
3. 需要立即就医的情况
4. 免责声明: AI建议仅供参考"""

    output = await run_agent_node(
        config, prompt, skill_tags=["medical"], state=state, agent_type="diagnosis", task=task,
    )
    return {
        "current_step": "adviser",
        "completed_steps": ["adviser"],
        "node_outputs": {"adviser": output},
        "recommendations": output,
        "final_output": output,
    }


def _create_diagnosis_workflow() -> StateGraph:
    graph = StateGraph(DiagnosisAgentState)

    graph.add_node("collector", _collector_node)
    graph.add_node("analyzer", _analyzer_node)
    graph.add_node("adviser", _adviser_node)

    graph.add_edge("collector", "analyzer")
    graph.add_edge("analyzer", "adviser")
    graph.add_edge("adviser", END)

    graph.set_entry_point("collector")

    return graph.compile(checkpointer=create_checkpointer())


_create_diagnosis_workflow.description = (
    "诊断工作流。信息收集 → 症状分析 → 分级建议。适用于医疗健康场景。"
)
_create_diagnosis_workflow.use_cases = "症状分析、健康咨询、分诊建议"
_create_diagnosis_workflow.step_count = 3

WorkflowRegistry.register("diagnosis_flow")(_create_diagnosis_workflow)
