"""智能分诊工作流。

Graph: collector → history → risk → danger → triage

第一阶段：症状收集 → 病史利用 → 风险评估 → 危险信号 → 分诊建议。
不进行确定性诊断，定位为风险评估与就医指导。
"""

from __future__ import annotations

from langgraph.constants import END
from langgraph.graph import StateGraph
from langchain_core.runnables import RunnableConfig

from haven.workflow.helpers import create_checkpointer, run_agent_node
from haven.workflow.registry import WorkflowRegistry
from haven.workflow.state import AgentState


class TriageAgentState(AgentState, total=False):
    """分诊工作流状态。"""

    symptoms: str
    collected_symptoms: str
    history_notes: str
    risk_level: str          # low / medium / high
    danger_signals: str      # 识别的危险信号
    triage_advice: str       # 分诊建议


# ====================================================================
# 节点函数
# ====================================================================


async def _collector_node(state: TriageAgentState, config: RunnableConfig) -> dict:
    """症状收集：根据用户描述，有针对性地追问 2-3 个最关键的问题。

    不过度追问——每次只问最紧急需要知道的信息。
    """
    task = state.get("task", "")
    already = state.get("collected_symptoms", "")

    prompt = f"""## 任务：症状收集

用户描述了以下情况：

{task}

{f'已收集到的信息：{already}' if already else '（尚未收集任何信息）'}

请：
1. 总结用户已提供的关键症状
2. 如果信息不足，追问 2-3 个最关键的问题（如持续时间、疼痛程度、伴随症状）
   不要一次性问太多问题。
3. 如果信息已经足够进行初步评估，说明"信息收集完成"。

注意：
- 这是分诊，不是诊断。不要告诉用户"你得了什么病"。
- 用关切、沉稳的语气。"""

    output = await run_agent_node(
        config, prompt,
        skill_tags=["medical"], state=state, agent_type="diagnosis", task=task,
    )
    return {
        "current_step": "collector",
        "completed_steps": ["collector"],
        "node_outputs": {"collector": output},
        "collected_symptoms": output,
    }


async def _history_node(state: TriageAgentState, config: RunnableConfig) -> dict:
    """病史收集：检查长期 Memory 中已有的病史，只追问 Memory 中没有的关键信息。"""
    task = state.get("task", "")
    symptoms = state.get("collected_symptoms", "")

    prompt = f"""## 任务：病史评估

用户主诉：{task}

已收集的症状信息：{symptoms}

你的系统上下文中可能包含用户的长期健康记录（如高血压、糖尿病、既往病史等）。
如果系统上下文中已有相关病史，直接引用并说明"根据您的既往记录"。
如果没有相关记录，简要询问 1-2 个关键病史问题。

请输出：
1. 已知病史（来自记忆）
2. 需要补充的关键信息（如有）
3. 对当前分诊的价值评估"""

    output = await run_agent_node(
        config, prompt,
        skill_tags=["medical"], state=state, agent_type="diagnosis", task=task,
    )
    return {
        "current_step": "history",
        "completed_steps": ["history"],
        "node_outputs": {"history": output},
        "history_notes": output,
    }


async def _risk_node(state: TriageAgentState, config: RunnableConfig) -> dict:
    """风险评估：基于症状+病史，给出 low / medium / high 风险评级。"""
    task = state.get("task", "")
    symptoms = state.get("collected_symptoms", "")
    history = state.get("history_notes", "")

    prompt = f"""## 任务：风险评估

基于以下信息进行风险评估：

主诉：{task}
症状信息：{symptoms}
病史信息：{history}

请输出：
1. 风险等级（必须从以下三个中选择一个）：low / medium / high
2. 评估依据（1-2 句话说明原因）

注意：
- 不确定时不升级风险等级
- 不要进行疾病诊断"""

    output = await run_agent_node(
        config, prompt,
        skill_tags=["medical"], state=state, agent_type="diagnosis", task=task,
    )
    # 从输出中提取风险等级
    risk = "medium"
    text_lower = output.lower()
    if "high" in text_lower or "高风险" in output:
        risk = "high"
    elif "low" in text_lower or "低风险" in output:
        risk = "low"

    return {
        "current_step": "risk",
        "completed_steps": ["risk"],
        "node_outputs": {"risk": output},
        "risk_level": risk,
    }


async def _danger_node(state: TriageAgentState, config: RunnableConfig) -> dict:
    """危险信号检测：识别需要立即就医的警示症状。"""
    task = state.get("task", "")
    symptoms = state.get("collected_symptoms", "")
    risk = state.get("risk_level", "medium")

    prompt = f"""## 任务：危险信号检测

检查以下信息中是否存在需要立即就医的危险信号：

主诉：{task}
症状：{symptoms}
风险等级：{risk}

需要重点识别的危险信号：
- 剧烈胸痛、胸闷
- 呼吸困难、窒息感
- 意识障碍、晕厥
- 持续高热（>39度超过3天）
- 大量出血
- 突发肢体无力、口齿不清（中风信号）

请输出：
1. 是否检测到危险信号（有/无）
2. 具体是哪些信号
3. 建议（如有信号，明确建议立即就医）"""

    output = await run_agent_node(
        config, prompt,
        skill_tags=["medical"], state=state, agent_type="diagnosis", task=task,
    )
    has_danger = "危险信号：有" in output or "检测到危险" in output or "立即就医" in output

    # 如果检测到危险信号，自动将风险升级为 high
    new_risk = "high" if has_danger else risk

    return {
        "current_step": "danger",
        "completed_steps": ["danger"],
        "node_outputs": {"danger": output},
        "danger_signals": output,
        "risk_level": new_risk,
    }


async def _triage_node(state: TriageAgentState, config: RunnableConfig) -> dict:
    """分诊建议：综合所有信息，给出最终分诊建议。"""
    task = state.get("task", "")
    symptoms = state.get("collected_symptoms", "")
    history = state.get("history_notes", "")
    risk = state.get("risk_level", "medium")
    danger = state.get("danger_signals", "")

    prompt = f"""## 任务：分诊建议

综合以下信息，给出智能分诊建议：

主诉：{task}
症状摘要：{symptoms}
病史：{history}
风险评估：{risk}
危险信号检测：{danger}

请以结构化方式输出分诊建议：
1. 分诊结论（从以下选择一项）：
   - 建议立即急诊
   - 建议24小时内就诊
   - 建议普通门诊
   - 建议观察并记录
2. 建议科室（如消化内科、心内科、急诊科等）
3. 原因说明（2-3 句话）
4. 注意事项

重要原则：
- 不要进行确定性诊断
- 这是 AI 辅助分诊建议，需医生最终确认
- 如果存在危险信号，必须建议立即就医
- 用友善、关切的语气"""

    output = await run_agent_node(
        config, prompt,
        skill_tags=["medical"], state=state, agent_type="diagnosis", task=task,
    )
    return {
        "current_step": "triage",
        "completed_steps": ["triage"],
        "node_outputs": {"triage": output},
        "triage_advice": output,
        "final_output": output,
    }


# ====================================================================
# 注册
# ====================================================================


def _create_triage_workflow() -> StateGraph:
    graph = StateGraph(TriageAgentState)

    graph.add_node("collector", _collector_node)
    graph.add_node("history", _history_node)
    graph.add_node("risk", _risk_node)
    graph.add_node("danger", _danger_node)
    graph.add_node("triage", _triage_node)

    graph.add_edge("collector", "history")
    graph.add_edge("history", "risk")
    graph.add_edge("risk", "danger")
    graph.add_edge("danger", "triage")
    graph.add_edge("triage", END)

    graph.set_entry_point("collector")
    return graph.compile(checkpointer=create_checkpointer())


_create_triage_workflow.description = (
    "智能分诊工作流。症状收集 → 病史利用 → 风险评估 → 危险信号检测 → 分诊建议。"
    "适用于医疗健康第一入口，不做疾病诊断，只做风险分层和就医指导。"
)
_create_triage_workflow.use_cases = "症状分诊、风险评估、就医指导、胸痛/发热/头晕等常见症状的初步评估"
_create_triage_workflow.step_count = 5

WorkflowRegistry.register("triage_flow")(_create_triage_workflow)
