"""七日血压趋势工具 —— 取数后交纯统计模块，绝不 LLM。"""

from __future__ import annotations

from managed_deepagents import ManagedDeepAgentRuntime

from application.messages import MSG
from application.trends import calculate_seven_day_trend, format_trend_message
from storage.database import DatabaseUnavailable, session_scope
from tools._helpers import (
    NO_IDENTITY_REPLY,
    degraded,
    has_consented,
    seven_day_records,
    uid_of,
)


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
            records = await seven_day_records(session, uid)
    except DatabaseUnavailable:
        return degraded()
    summary = calculate_seven_day_trend(records)
    return format_trend_message(summary)
