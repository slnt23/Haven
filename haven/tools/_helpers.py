"""工具共享辅助：调用者识别、同意闸门、共用取数口径、确定性时间解析。

供 `tools/` 与 `middleware/` 双方使用：同一份数据（同意状态、近 7 天血压）
必须只有一处查询，各写一份迟早会分叉成两套数字。

日期类解析（ISO / 中文年月日 / 纯年份）在 `application/onboarding.parse_date`
—— 那是档案字段校验的唯一真相源，本模块不再重复实现一份。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from managed_deepagents import ManagedDeepAgentRuntime
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from storage.database import caller_user_id
from storage.models import BloodPressure, ConsentRecord
from safety.degradation import DB_DEGRADED_RESPONSE

#: 单租户部署下，走到这里只有一种原因：调用者不是本部署服务的本人。
#: 真正的原因（期望/实际 user id）在服务端日志里 —— 不回显给调用者。
NO_IDENTITY_REPLY = "本服务只为指定用户提供服务，当前调用者不在服务范围内。"

#: 允许的时钟偏差：设备时钟略快于服务器时不算“未来”。
_FUTURE_TOLERANCE = timedelta(minutes=5)

#: 「近 7 天」的窗口与读取上限。
SEVEN_DAY_WINDOW = timedelta(days=7)
MAX_SEVEN_DAY_RECORDS = 500


def uid_of(runtime: ManagedDeepAgentRuntime) -> str | None:
    return caller_user_id(runtime)


async def has_consented(session: AsyncSession, uid: str) -> bool:
    stmt = select(ConsentRecord).where(ConsentRecord.user_id == uid).limit(1)
    result = await session.execute(stmt)
    return result.scalars().first() is not None


async def seven_day_records(session: AsyncSession, uid: str) -> list[BloodPressure]:
    """该用户近 7 天的血压记录（时间升序）。

    这是「近 7 天」的**唯一取数口径** —— `get_seven_day_trend`（用户向）与
    记忆注入（模型向）共用，两处渲染出的记录数/均值/最高/达标率才会逐项
    一致。上限是成本兜底，不是业务规则：单列索引下按时间倒序扫。
    """
    stmt = (
        select(BloodPressure)
        .where(
            BloodPressure.user_id == uid,
            BloodPressure.measured_at >= datetime.now(UTC) - SEVEN_DAY_WINDOW,
        )
        .order_by(BloodPressure.measured_at.asc())
        .limit(MAX_SEVEN_DAY_RECORDS)
    )
    return list((await session.execute(stmt)).scalars().all())


def parse_measured_at(text: str | None) -> datetime | None:
    """解析测量时间；date-only 视为当天 00:00 UTC；返回带时区 UTC。"""
    if not text:
        return datetime.now(UTC)
    text = text.strip()
    try:
        value = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def is_future(value: datetime) -> bool:
    return value > datetime.now(UTC) + _FUTURE_TOLERANCE


def degraded() -> str:
    return DB_DEGRADED_RESPONSE
