"""软件开发工作流。

Graph: planner → architect → coder → reviewer → tester
                                     ▲              │
                                     │    fail      │
                                     └──────────────┘ (retry ≤ 3)
"""

from __future__ import annotations

from operator import add
from typing import Annotated

from langgraph.constants import END
from langgraph.graph import StateGraph
from langchain_core.runnables import RunnableConfig

from haven.workflow.helpers import create_checkpointer
from haven.workflow.helpers import run_agent_node
from haven.workflow.registry import WorkflowRegistry
from haven.workflow.state import AgentState


class DevAgentState(AgentState, total=False):
    """软件开发工作流状态。"""

    architecture_doc: str
    source_code: str
    code_language: str
    review_feedback: str
    review_score: float
    review_blockers: Annotated[list[str], add]
    test_report: str
    test_passed: bool
    test_failures: Annotated[list[str], add]


# ====================================================================
# 节点函数
# ====================================================================


async def _planner_node(state: DevAgentState, config: RunnableConfig) -> dict:
    task = state.get("task", "")
    prompt = f"""## 任务：需求分析

分析用户需求，明确要做的事情。

用户需求: {task}

输出:
1. 需求概述（一句话）
2. 功能清单
3. 技术约束
4. 验收标准"""

    output = await run_agent_node(
        config, prompt, skill_tags=["development"], state=state, agent_type="coder", task=task,
    )
    return _node_result("planner", output)


async def _architect_node(state: DevAgentState, config: RunnableConfig) -> dict:
    task = state.get("task", "")
    plan = state.get("node_outputs", {}).get("planner", "")
    prompt = f"""## 任务：架构设计

基于需求分析设计系统架构。

原始需求: {task}

需求分析:
{plan}

输出:
1. 架构模式
2. 技术栈选择
3. 目录/模块结构
4. 关键接口定义"""

    output = await run_agent_node(
        config, prompt, skill_tags=["development"], state=state, agent_type="coder", task=task,
    )
    result = _node_result("architect", output)
    result["architecture_doc"] = output
    return result


async def _coder_node(state: DevAgentState, config: RunnableConfig) -> dict:
    task = state.get("task", "")
    arch = state.get("architecture_doc", "")
    review_feedback = state.get("node_outputs", {}).get("reviewer", "")
    test_failures = state.get("test_failures", [])

    parts = ["## 任务：编写代码\n", f"需求: {task}", f"架构设计: {arch}"]

    retries = state.get("node_retry_counts", {}).get("coder", 0)
    if retries > 0:
        parts.append("\n## 这是重新编码，以下是你上次的问题:")
        if review_feedback:
            parts.append(f"\n### Review 反馈:\n{review_feedback}")
        if test_failures:
            parts.append("\n### 测试失败:\n" + "\n".join(f"- {f}" for f in test_failures))
        parts.append("\n请修正所有问题后重新生成代码。")

    parts.append("\n输出: 完整的可运行代码，包含注释。")

    output = await run_agent_node(
        config, "\n".join(parts), skill_tags=["development"], state=state, agent_type="coder", task=task,
    )
    result = _node_result("coder", output)
    result["source_code"] = _extract_code_block(output)
    return result


async def _reviewer_node(state: DevAgentState, config: RunnableConfig) -> dict:
    task = state.get("task", "")
    prompt = f"""## 任务：代码审查

审查以下代码:

{state.get("source_code", "")}

原始需求: {task}

按维度评分（0-100）: 功能正确性(40) 代码质量(20) 安全性(20) 性能(10) 可维护性(10)

输出格式:
- 总分: X/100
- 通过: yes/no (>= 70 为通过)
- 阻塞项:
- 建议项:"""

    output = await run_agent_node(
        config, prompt, skill_tags=["review"], state=state, agent_type="coder", task=task,
    )
    result = _node_result("reviewer", output)
    result["review_feedback"] = output
    result["review_score"] = _parse_score(output)
    result["review_blockers"] = _parse_blockers(output)
    return result


async def _tester_node(state: DevAgentState, config: RunnableConfig) -> dict:
    task = state.get("task", "")
    prompt = f"""## 任务：测试验证

编写测试并验证以下代码:

{state.get("source_code", "")}

原始需求: {task}

输出:
- 通过: yes/no
- 失败项:
- 测试覆盖:"""

    output = await run_agent_node(
        config, prompt, skill_tags=["development"], state=state, agent_type="coder", task=task,
    )
    passed = "通过: yes" in output or "通过：是" in output or "PASS" in output.upper()
    result = _node_result("tester", output)
    result["test_report"] = output
    result["test_passed"] = passed
    result["test_failures"] = _parse_failures(output)
    result["final_output"] = output
    return result


# ====================================================================
# 路由器
# ====================================================================


def _test_router(state: DevAgentState) -> str:
    if state.get("test_passed", False):
        return END
    retries = state.get("node_retry_counts", {}).get("coder", 0)
    if retries >= state.get("max_retries_per_node", 3):
        return END
    return "coder"


def _create_dev_workflow() -> StateGraph:
    """创建软件开发工作流。"""
    graph = StateGraph(DevAgentState)

    graph.add_node("planner", _planner_node)
    graph.add_node("architect", _architect_node)
    graph.add_node("coder", _coder_node)
    graph.add_node("reviewer", _reviewer_node)
    graph.add_node("tester", _tester_node)

    graph.add_edge("planner", "architect")
    graph.add_edge("architect", "coder")
    graph.add_edge("coder", "reviewer")
    graph.add_edge("reviewer", "tester")

    graph.add_conditional_edges("tester", _test_router)

    graph.set_entry_point("planner")

    return graph.compile(checkpointer=create_checkpointer())


# ====================================================================
# 辅助函数
# ====================================================================


def _node_result(name: str, output: str) -> dict:
    return {
        "current_step": name,
        "completed_steps": [name],
        "node_outputs": {name: output},
    }


def _extract_code_block(text: str) -> str:
    if "```" in text:
        parts = text.split("```")
        for i, part in enumerate(parts):
            if i % 2 == 1:
                lines = part.split("\n")
                if lines[0].strip() in (
                    "", "python", "js", "go", "rust", "shell", "bash",
                    "sql", "json", "yaml", "html", "css", "java", "ts",
                    "typescript", "cpp", "c",
                ):
                    return "\n".join(lines[1:]).strip()
                return part.strip()
    return text


def _parse_score(text: str) -> float:
    import re

    match = re.search(r"总分[：:]\s*(\d+)/?\s*100", text)
    return float(match.group(1)) if match else 0.0


def _parse_blockers(text: str) -> list[str]:
    blockers: list[str] = []
    in_section = False
    for line in text.split("\n"):
        stripped = line.strip()
        if "阻塞" in stripped:
            in_section = True
            continue
        if in_section and stripped.startswith("-"):
            blockers.append(stripped.lstrip("- "))
        elif in_section and stripped == "":
            break
    return blockers


def _parse_failures(text: str) -> list[str]:
    failures: list[str] = []
    in_section = False
    for line in text.split("\n"):
        stripped = line.strip()
        if "失败" in stripped and ":" in stripped:
            in_section = True
            continue
        if in_section and stripped.startswith("-"):
            failures.append(stripped.lstrip("- "))
        elif in_section and stripped == "":
            break
    return failures


# ====================================================================
# 注册
# ====================================================================

_create_dev_workflow.description = (
    "软件开发工作流。需求分析 → 架构设计 → 编码 → 审查 → 测试。支持失败重试（最多3次）。"
)
_create_dev_workflow.use_cases = "代码生成、Bug修复、架构设计、功能开发"
_create_dev_workflow.step_count = 5

WorkflowRegistry.register("dev_flow")(_create_dev_workflow)
