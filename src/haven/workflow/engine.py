"""WorkflowEngine —— 基于 LangGraph 的工作流执行引擎。

Workflow 本质也是 Execution：接收任务，返回 WorkflowResult。
所有 Workflow 必须遵守输出契约：state["final_output"]。

Pipeline 只读取 WorkflowResult.output，不接触 raw state dict。
"""

from __future__ import annotations

import logging
from typing import Any, AsyncIterator

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph.state import CompiledStateGraph

from haven.session.models import Session
from haven.workflow.result import WorkflowResult

logger = logging.getLogger("haven.workflow.engine")


class WorkflowEngine:
    """LangGraph 工作流执行引擎。

    封装工作流的构建与执行。每个注册的工作流是一个 factory 函数，
    返回编译后的 LangGraph StateGraph。

    输出契约：
      Workflow 的终端节点必须设置 state["final_output"]。
      Engine 只读取此字段，不做任何猜测或 fallback。
    """

    def __init__(self, registry: Any = None) -> None:
        self._registry = registry
        self._checkpointer = MemorySaver()

    async def run(
        self,
        workflow_name: str,
        task: str,
        session: Session,
        *,
        plan_skills: list[str] | None = None,
        agent: Any = None,
        agents: dict[str, Any] | None = None,
        context_builder: Any = None,
        dispatcher: Any = None,
    ) -> WorkflowResult:
        """执行工作流，返回 WorkflowResult。"""
        graph = self._build(workflow_name)
        state = self._make_state(workflow_name, task, session, plan_skills)

        config = {
            "configurable": {
                "thread_id": session.id,
                "agent": agent,
                "agents": agents or {},
                "context_builder": context_builder,
                "dispatcher": dispatcher,
            }
        }

        try:
            result_state = await graph.ainvoke(state, config=config)
        except Exception as exc:
            logger.error("工作流 '%s' 执行失败: %s", workflow_name, exc)
            return WorkflowResult(
                output=f"[错误] 工作流执行失败: {exc}",
                errors=[str(exc)],
            )

        wf_result = WorkflowResult.from_state(result_state)

        if not wf_result.output:
            logger.warning(
                "工作流 '%s' 未设置 final_output。"
                "请确保终端节点在 state 中设置 'final_output' 字段。",
                workflow_name,
            )

        return wf_result

    async def run_stream(
        self,
        workflow_name: str,
        task: str,
        session: Session,
        *,
        plan_skills: list[str] | None = None,
        agent: Any = None,
        agents: dict[str, Any] | None = None,
        context_builder: Any = None,
        dispatcher: Any = None,
    ) -> AsyncIterator:
        """流式执行工作流。yield token/status 事件并通过最终 state 提取输出。"""
        from haven.infrastructure.types import StreamChunk

        graph = self._build(workflow_name)
        state = self._make_state(workflow_name, task, session, plan_skills)

        config = {
            "configurable": {
                "thread_id": session.id,
                "agent": agent,
                "agents": agents or {},
                "context_builder": context_builder,
                "dispatcher": dispatcher,
            }
        }

        final_state: dict = {}
        try:
            async for event in graph.astream_events(state, config=config):
                kind = event.get("event", "")
                if kind == "on_chat_model_stream":
                    chunk = event.get("data", {}).get("chunk")
                    if chunk and hasattr(chunk, "content") and chunk.content:
                        yield StreamChunk(kind="text", content=chunk.content)
                elif kind == "on_tool_start":
                    yield StreamChunk(kind="status", content=f"调用工具: {event.get('name', 'unknown')}")
                elif kind == "on_tool_end":
                    yield StreamChunk(kind="status", content=f"工具完成: {event.get('name', 'unknown')}")
                elif kind == "on_chain_end" and event.get("name") == workflow_name:
                    final_state = event.get("data", {}).get("output", {})
        except Exception as exc:
            logger.error("工作流 '%s' 流式执行失败: %s", workflow_name, exc)
            yield StreamChunk(kind="text", content=f"[错误] {exc}")
            return

        # 流式输出 token 后，附加最终结果文本
        wf_result = WorkflowResult.from_state(final_state)
        if wf_result.output:
            yield StreamChunk(kind="text", content="\n" + wf_result.output)
        else:
            logger.warning(
                "工作流 '%s' 未设置 final_output。"
                "请确保终端节点在 state 中设置 'final_output' 字段。",
                workflow_name,
            )

    def _build(self, workflow_name: str) -> CompiledStateGraph:
        if self._registry is None:
            raise RuntimeError("WorkflowRegistry 未初始化")
        return self._registry.build(workflow_name)

    def _make_state(
        self,
        wf_name: str,
        task: str,
        session: Session,
        plan_skills: list[str] | None = None,
    ) -> dict:
        base = {
            "task": task,
            "session_id": session.id,
            "messages": [],
            "errors": [],
            "completed_steps": [],
            "current_step": "",
            "node_outputs": {},
            "node_retry_counts": {},
            "max_retries_per_node": 3,
            "status": "pending",
            "final_output": "",
            "started_at": 0.0,
            "plan_skills": list(plan_skills) if plan_skills else [],
        }
        if "dev" in wf_name:
            base.update({
                "architecture_doc": "", "source_code": "", "code_language": "python",
                "review_feedback": "", "review_score": 0.0, "review_blockers": [],
                "test_report": "", "test_passed": False, "test_failures": [],
            })
        elif "research" in wf_name:
            base.update({
                "research_topic": "", "raw_findings": [], "analyzed_insights": "",
                "final_report": "", "sources": [],
            })
        elif "diagnosis" in wf_name:
            base.update({
                "symptoms": "", "collected_info": "", "possible_causes": "",
                "diagnosis": "", "recommendations": [],
            })
        return base
