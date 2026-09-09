"""七日血压趋势工具 —— 取数后交纯统计模块，绝不 LLM。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from managed_deepagents import ManagedDeepAgentRuntime
from sqlalchemy import select

from application.messages import MSG
from application.trends import calculate_seven_day_trend, format_trend_message
from storage.database import DatabaseUnavailable, session_scope
from storage.models import BloodPressure
from tools._helpers import NO_IDENTITY_REPLY, degraded, has_consented, uid_of


async def get_seven_day_trend(runtime: ManagedDeepAgentRuntime = None) -> str:
    """查看最近 7 天的血压趋势统计（记录数、均值、最高/最低、达标率、方向）。
    仅呈现确定性统计，不做诊断。"""
    uid = uid_of(runtime)
    if uid is None:
        return NO_IDENTITY_REPLY
    try:
        async with session_scope() as session:
            if not await has_consented(session, uid):
                return MSG.consent_required
            records = (
                await session.execute(
                    select(BloodPressure)
                    .where(
                        BloodPressure.user_id == uid,
                        BloodPressure.measured_at
                        >= datetime.now(UTC) - timedelta(days=7),
                    )
                    .order_by(BloodPressure.measured_at.asc())
                    .limit(500)
                )
            ).scalars().all()
    except DatabaseUnavailable:
        return degraded()
    summary = calculate_seven_day_trend(list(records))
    return format_trend_message(summary)
