"""诊断工作流。

Graph: collector → analyzer → adviser → END
"""

from __future__ import annotations

from langgraph.constants import END
from langgraph.graph import StateGraph
from langgraph.runtime import Runtime

from haven.workflows.graph import create_checkpointer
from haven.workflows.registry import WorkflowRegistry
from haven.workflows.state import DiagnosisAgentState


async def _collector_node(state: DiagnosisAgentState, config: Runtime) -> dict:
    rt = config["configurable"]["runtime"]

    prompt = f"""## 任务：信息收集

收集用户信息以辅助诊断。

用户描述: {state.get("task", "")}

询问并收集: 持续时间、伴随症状、既往病史、用药情况。"""

    output = await rt.run(prompt, active_skills=_skills(["medical"]), use_memory=True)
    return {
        "current_step": "collector",
        "completed_steps": ["collector"],
        "node_outputs": {"collector": output},
        "collected_info": output,
    }


async def _analyzer_node(state: DiagnosisAgentState, config: Runtime) -> dict:
    rt = config["configurable"]["runtime"]

    prompt = f"""## 任务：症状分析

分析症状并给出可能的原因。

症状: {state.get("task", "")}
已收集信息: {state.get("collected_info", "")}

输出:
1. 可能的病因列表（按可能性排序）
2. 每种可能性的置信度
3. 建议的下一步"""

    output = await rt.run(prompt, active_skills=_skills(["medical"]), use_memory=True)
    return {
        "current_step": "analyzer",
        "completed_steps": ["analyzer"],
        "node_outputs": {"analyzer": output},
        "possible_causes": output,
    }


async def _adviser_node(state: DiagnosisAgentState, config: Runtime) -> dict:
    rt = config["configurable"]["runtime"]

    prompt = f"""## 任务：给出建议

基于分析给出分级的医疗建议。

症状: {state.get("task", "")}
分析结果: {state.get("possible_causes", "")}

输出:
1. 自我处理建议
2. 建议就医的情况
3. 需要立即就医的情况
4. 免责声明: AI建议仅供参考"""

    output = await rt.run(prompt, active_skills=_skills(["medical"]), use_memory=True)
    return {
        "current_step": "adviser",
        "completed_steps": ["adviser"],
        "node_outputs": {"adviser": output},
        "recommendations": output,
    }


def _skills(names: list[str]) -> list:
    from haven.skills.registry import SkillRegistry

    skills = []
    for n in names:
        try:
            skills.append(SkillRegistry.get(n))
        except KeyError:
            pass
    return skills


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
