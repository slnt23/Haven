"""调研工作流。

Graph: searcher → analyst ─┬→ synthesizer → END
                   ▲        │
                   │ 缺口   │
                   └────────┘ (retry ≤ 3)
"""

from __future__ import annotations

from operator import add
from typing import Annotated

from langchain_core.runnables import RunnableConfig
from langgraph.graph import StateGraph

from haven.runtime.registry import WorkflowRegistry
from haven.runtime.state import AgentState
from haven.runtime.workflows import create_checkpointer
from haven.runtime.workflows._helpers import run_agent_node


class ResearchAgentState(AgentState, total=False):
    """调研工作流状态。"""

    research_topic: str
    raw_findings: Annotated[list[str], add]
    analyzed_insights: str
    final_report: str
    sources: Annotated[list[str], add]


async def _searcher_node(state: ResearchAgentState, config: RunnableConfig) -> dict:
    task = state.get("task", "")
    prompt = f"""## 任务：信息搜集

搜索以下主题的相关信息:

{task}

要求: 从多个来源搜集信息，记录来源URL，提炼核心观点。"""

    output = await run_agent_node(
        config, prompt, state=state, agent_type="researcher", task=task,
    )
    retries = dict(state.get("node_retry_counts", {}))
    retries["searcher"] = retries.get("searcher", 0) + 1
    return {
        "current_step": "searcher",
        "completed_steps": ["searcher"],
        "node_outputs": {"searcher": output},
        "raw_findings": [output],
        "node_retry_counts": retries,
    }


async def _analyst_node(state: ResearchAgentState, config: RunnableConfig) -> dict:
    task = state.get("task", "")
    findings = "\n---\n".join(state.get("raw_findings", []))
    prompt = f"""## 任务：信息分析

分析以下信息，识别关键洞察:

{findings}

原始主题: {task}

输出:
1. 核心发现 (3-5条)
2. 矛盾观点
3. 数据可信度评估
4. 仍存在的知识缺口"""

    output = await run_agent_node(
        config, prompt, skill_tags=["analysis"], state=state, agent_type="researcher", task=task,
    )
    return {
        "current_step": "analyst",
        "completed_steps": ["analyst"],
        "node_outputs": {"analyst": output},
        "analyzed_insights": output,
    }


async def _synthesizer_node(state: ResearchAgentState, config: RunnableConfig) -> dict:
    task = state.get("task", "")
    prompt = f"""## 任务：撰写报告

基于分析撰写结构化报告。

主题: {task}

分析结果: {state.get("analyzed_insights", "")}

报告格式（Markdown）:
# {task} — 调研报告
## 概述 / ## 核心发现 / ## 详细分析 / ## 结论与建议 / ## 信息来源"""

    output = await run_agent_node(
        config, prompt, skill_tags=["writing", "synthesis"], state=state, agent_type="researcher", task=task,
    )
    return {
        "current_step": "synthesizer",
        "completed_steps": ["synthesizer"],
        "node_outputs": {"synthesizer": output},
        "final_report": output,
    }


def _research_router(state: ResearchAgentState) -> str:
    insights = state.get("analyzed_insights", "")
    search_count = state.get("node_retry_counts", {}).get("searcher", 0)
    if "知识缺口" in insights and search_count < 3:
        return "searcher"
    return "synthesizer"


def _create_research_workflow() -> StateGraph:
    graph = StateGraph(ResearchAgentState)

    graph.add_node("searcher", _searcher_node)
    graph.add_node("analyst", _analyst_node)
    graph.add_node("synthesizer", _synthesizer_node)

    graph.add_edge("searcher", "analyst")
    graph.add_conditional_edges("analyst", _research_router)

    graph.set_entry_point("searcher")

    return graph.compile(checkpointer=create_checkpointer())


_create_research_workflow.description = (
    "调研工作流。信息搜集 → 分析 → 报告生成。存在知识缺口时自动补充搜索。"
)
_create_research_workflow.use_cases = "技术调研、竞品分析、文献综述、市场研究"
_create_research_workflow.step_count = 3

WorkflowRegistry.register("research_flow")(_create_research_workflow)
