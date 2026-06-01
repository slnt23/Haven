"""WorkflowNode — 工作流节点的抽象基类 + 内置节点。

每个节点 = Runtime.run() 的一次调用，使用特定 Skill + prompt。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
import logging
from typing import Any

from haven.workflows.state import (
    DevWorkflowState,
    DiagnosisWorkflowState,
    ResearchWorkflowState,
    WorkflowState,
)

logger = logging.getLogger("haven.workflow.node")


class WorkflowNode(ABC):
    """工作流节点抽象基类。

    子类实现:
      - skill_name: str          节点使用的 skill 名
      - _build_prompt(state)     根据 state 构建 Runtime prompt
      - _process_output(output, state)  处理输出 → state 更新 dict

    ``__call__`` 符合 LangGraph node 签名: (state) → {update_dict}
    """

    name: str = ""
    skill_name: str | None = None
    max_retries: int = 0

    async def __call__(self, state: WorkflowState) -> dict[str, Any]:
        runtime = state._runtime
        prompt = self._build_prompt(state)

        active_skills = [self.skill_name] if self.skill_name else []

        try:
            output = await runtime.run(
                prompt,
                active_skills=self._resolve_skills(state, active_skills),
                use_memory=True,
            )
        except Exception as exc:
            return self._handle_error(state, exc)

        updates = self._process_output(output, state)
        updates["current_node"] = self.name
        updates["node_outputs"] = {
            **state.node_outputs,
            self.name: output,
        }
        return updates

    @abstractmethod
    def _build_prompt(self, state: WorkflowState) -> str: ...

    def _process_output(self, output: str, state: WorkflowState) -> dict[str, Any]:
        return {}

    @staticmethod
    def _resolve_skills(state: WorkflowState, names: list[str]) -> list[Any]:
        from haven.skills.registry import SkillRegistry

        skills = []
        for name in names:
            try:
                skills.append(SkillRegistry.get(name))
            except KeyError:
                pass
        return skills

    def _handle_error(self, state: WorkflowState, exc: Exception) -> dict[str, Any]:
        logger.error("Node '%s' failed: %s", self.name, exc)
        return {
            "errors": [*state.errors, f"[{self.name}] {exc}"],
            "status": "failed",
            "current_node": self.name,
        }


# ====================================================================
# 软件开发工作流节点
# ====================================================================


class PlannerNode(WorkflowNode):
    name = "planner"
    skill_name = "coder"

    def _build_prompt(self, state: DevWorkflowState) -> str:
        return f"""## 任务：需求分析

分析用户需求，明确要做的事情。

用户需求: {state.task}

输出:
1. 需求概述（一句话）
2. 功能清单
3. 技术约束
4. 验收标准"""


class ArchitectNode(WorkflowNode):
    name = "architect"
    skill_name = "coder"

    def _build_prompt(self, state: DevWorkflowState) -> str:
        plan = state.node_outputs.get("planner", "")
        return f"""## 任务：架构设计

基于需求分析设计系统架构。

原始需求: {state.task}

需求分析:
{plan}

输出:
1. 架构模式
2. 技术栈选择
3. 目录/模块结构
4. 关键接口定义"""

    def _process_output(self, output: str, state: DevWorkflowState) -> dict:
        return {"architecture_doc": output}


class CoderNode(WorkflowNode):
    name = "coder"
    skill_name = "coder"
    max_retries = 3

    def _build_prompt(self, state: DevWorkflowState) -> str:
        arch = state.architecture_doc
        review_feedback = state.node_outputs.get("reviewer", "")
        test_failures = state.test_failures

        parts = ["## 任务：编写代码\n", f"需求: {state.task}", f"架构设计: {arch}"]

        if state.node_retry_counts.get("coder", 0) > 0:
            parts.append("\n## 这是重新编码，以下是你上次的问题:")
            if review_feedback:
                parts.append(f"\n### Review 反馈:\n{review_feedback}")
            if test_failures:
                parts.append("\n### 测试失败:\n" + "\n".join(f"- {f}" for f in test_failures))
            parts.append("\n请修正所有问题后重新生成代码。")

        parts.append("\n输出: 完整的可运行代码，包含注释。")
        return "\n".join(parts)

    def _process_output(self, output: str, state: DevWorkflowState) -> dict:
        return {"source_code": _extract_code_block(output)}


class ReviewerNode(WorkflowNode):
    name = "reviewer"
    skill_name = "code_review"

    def _build_prompt(self, state: DevWorkflowState) -> str:
        return f"""## 任务：代码审查

审查以下代码:

{state.source_code}

原始需求: {state.task}

按维度评分（0-100）: 功能正确性(40) 代码质量(20) 安全性(20) 性能(10) 可维护性(10)

输出格式:
- 总分: X/100
- 通过: yes/no (>= 70 为通过)
- 阻塞项:
- 建议项:"""

    def _process_output(self, output: str, state: DevWorkflowState) -> dict:
        score = _parse_score(output)
        return {
            "review_feedback": output,
            "review_score": score,
            "review_blockers": _parse_blockers(output),
        }


class TesterNode(WorkflowNode):
    name = "tester"
    skill_name = "coder"

    def _build_prompt(self, state: DevWorkflowState) -> str:
        return f"""## 任务：测试验证

编写测试并验证以下代码:

{state.source_code}

原始需求: {state.task}

输出:
- 通过: yes/no
- 失败项:
- 测试覆盖:"""

    def _process_output(self, output: str, state: DevWorkflowState) -> dict:
        passed = "通过: yes" in output or "通过：是" in output or "PASS" in output.upper()
        return {
            "test_report": output,
            "test_passed": passed,
            "test_failures": _parse_failures(output),
        }


# ====================================================================
# 研究工作流节点
# ====================================================================


class SearcherNode(WorkflowNode):
    name = "searcher"
    skill_name = None

    def _build_prompt(self, state: ResearchWorkflowState) -> str:
        return f"""## 任务：信息搜集

搜索以下主题的相关信息:

{state.task}

要求: 从多个来源搜集信息，记录来源URL，提炼核心观点。"""

    def _process_output(self, output: str, state: ResearchWorkflowState) -> dict:
        findings = list(state.raw_findings)
        findings.append(output)
        return {"raw_findings": findings}


class AnalystNode(WorkflowNode):
    name = "analyst"
    skill_name = "data_analysis"

    def _build_prompt(self, state: ResearchWorkflowState) -> str:
        findings = "\n---\n".join(state.raw_findings)
        return f"""## 任务：信息分析

分析以下信息，识别关键洞察:

{findings}

原始主题: {state.task}

输出:
1. 核心发现 (3-5条)
2. 矛盾观点
3. 数据可信度评估
4. 仍存在的知识缺口"""

    def _process_output(self, output: str, state: ResearchWorkflowState) -> dict:
        return {"analyzed_insights": output}


class SynthesizerNode(WorkflowNode):
    name = "synthesizer"
    skill_name = "summarization"

    def _build_prompt(self, state: ResearchWorkflowState) -> str:
        return f"""## 任务：撰写报告

基于分析撰写结构化报告。

主题: {state.task}

分析结果: {state.analyzed_insights}

报告格式（Markdown）:
# {state.task} — 调研报告
## 概述 / ## 核心发现 / ## 详细分析 / ## 结论与建议 / ## 信息来源"""

    def _process_output(self, output: str, state: ResearchWorkflowState) -> dict:
        return {"final_report": output}


# ====================================================================
# 诊断工作流节点
# ====================================================================


class CollectorNode(WorkflowNode):
    name = "collector"
    skill_name = "medical"

    def _build_prompt(self, state: DiagnosisWorkflowState) -> str:
        return f"""## 任务：信息收集

收集用户信息以辅助诊断。

用户描述: {state.task}

询问并收集: 持续时间、伴随症状、既往病史、用药情况。"""

    def _process_output(self, output: str, state: DiagnosisWorkflowState) -> dict:
        return {"collected_info": output}


class AnalyzerNode(WorkflowNode):
    name = "analyzer"
    skill_name = "medical"

    def _build_prompt(self, state: DiagnosisWorkflowState) -> str:
        return f"""## 任务：症状分析

分析症状并给出可能的原因。

症状: {state.task}
已收集信息: {state.collected_info}

输出:
1. 可能的病因列表（按可能性排序）
2. 每种可能性的置信度
3. 建议的下一步"""

    def _process_output(self, output: str, state: DiagnosisWorkflowState) -> dict:
        return {"possible_causes": output}


class AdviserNode(WorkflowNode):
    name = "adviser"
    skill_name = "medical"

    def _build_prompt(self, state: DiagnosisWorkflowState) -> str:
        return f"""## 任务：给出建议

基于分析给出分级的医疗建议。

症状: {state.task}
分析结果: {state.possible_causes}

输出:
1. 自我处理建议
2. 建议就医的情况
3. 需要立即就医的情况
4. 免责声明: AI建议仅供参考"""

    def _process_output(self, output: str, state: DiagnosisWorkflowState) -> dict:
        return {"recommendations": output}


# ====================================================================
# 辅助函数
# ====================================================================


def _extract_code_block(text: str) -> str:
    if "```" in text:
        parts = text.split("```")
        for i, part in enumerate(parts):
            if i % 2 == 1:
                lines = part.split("\n")
                if lines[0].strip() in (
                    "",
                    "python",
                    "js",
                    "go",
                    "rust",
                    "shell",
                    "bash",
                    "sql",
                    "json",
                    "yaml",
                    "html",
                    "css",
                    "java",
                    "ts",
                    "typescript",
                    "cpp",
                    "c",
                ):
                    return "\n".join(lines[1:]).strip()
                return part.strip()
    return text


def _parse_score(text: str) -> float:
    import re

    match = re.search(r"总分[：:]\s*(\d+)/?\s*100", text)
    return float(match.group(1)) if match else 0.0


def _parse_blockers(text: str) -> list[str]:
    blockers = []
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
    failures = []
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
