"""Executor —— 执行编排器，统一入口。"""

from __future__ import annotations

import logging
import uuid
from typing import Any, AsyncIterator

from haven.kernel.trace import TraceContext, set_current_trace
from haven.session.models import Session
from haven.execution.request import ExecutionRequest, ExecutionPlan
from haven.execution.response import ExecutionResponse
from haven.execution.planner import Planner
from haven.execution.pipeline import ExecutionPipeline

logger = logging.getLogger("haven.execution.executor")


class Executor:
    """执行编排器。

    持有 Planner（规划）和 Pipeline（执行），
    为 Runtime 提供统一的 execute() / execute_stream() 入口。

    Runtime 只能通过 Executor 执行任务，不能直接接触 Agent。
    """

    def __init__(
        self,
        planner: Planner,
        pipeline: ExecutionPipeline,
        *,
        session_manager: Any = None,
    ) -> None:
        self._planner = planner
        self._pipeline = pipeline
        self._session_manager = session_manager

    # ------------------------------------------------------------------
    # 公开 API
    # ------------------------------------------------------------------

    async def execute(self, request: ExecutionRequest) -> ExecutionResponse:
        """执行完整请求：规划 → 执行 → 响应。"""
        trace_id = request.trace_id or str(uuid.uuid4())
        ctx = TraceContext(trace_id=trace_id, span_id=str(uuid.uuid4()))
        set_current_trace(ctx)

        plan: ExecutionPlan | None = None
        try:
            session = self._get_session(request.session_id)
            plan = await self._planner.plan(request)
            result = await self._pipeline.run(plan, request.task, session)
        except Exception as exc:
            logger.error("执行失败: %s", exc)
            return ExecutionResponse(
                result=f"[错误] {exc}",
                trace_id=trace_id,
                plan_summary=plan.goal if plan else None,
                errors=[str(exc)],
            )

        return ExecutionResponse(
            result=result,
            trace_id=trace_id,
            plan_summary=plan.goal if plan else None,
            agent_type=plan.agent_type if plan else None,
            skills_used=list(plan.skills) if plan else [],
        )

    async def execute_stream(
        self, request: ExecutionRequest,
    ) -> AsyncIterator:
        """流式执行版本。"""
        from haven.infrastructure.types import StreamChunk
        trace_id = request.trace_id or str(uuid.uuid4())
        ctx = TraceContext(trace_id=trace_id, span_id=str(uuid.uuid4()))
        set_current_trace(ctx)

        plan: ExecutionPlan | None = None
        try:
            session = self._get_session(request.session_id)
            plan = await self._planner.plan(request)
            yield StreamChunk(
                kind="plan",
                content=f"{plan.intent} → {plan.agent_type} (复杂度: {plan.complexity})",
            )
            async for chunk in self._pipeline.run_stream(plan, request.task, session):
                yield chunk
        except Exception as exc:
            logger.error("流式执行失败: %s", exc)
            yield StreamChunk(kind="text", content=f"[错误] {exc}")

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------

    def _get_session(self, session_id: str) -> Session:
        if self._session_manager is not None:
            return self._session_manager.get_or_create(session_id)
        return Session(id=session_id)
