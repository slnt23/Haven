"""工具共享辅助：调用者识别、同意闸门、确定性时间解析。"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime, timedelta

from managed_deepagents import ManagedDeepAgentRuntime
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.database import caller_user_id
from db.models import ConsentRecord
from safety.degradation import DB_DEGRADED_RESPONSE

NO_IDENTITY_REPLY = "暂时无法识别调用者身份，请稍后再试。"

#: 允许的时钟偏差：设备时钟略快于服务器时不算“未来”。
_FUTURE_TOLERANCE = timedelta(minutes=5)


def uid_of(runtime: ManagedDeepAgentRuntime) -> str | None:
    return caller_user_id(runtime)


async def has_consented(session: AsyncSession, uid: str) -> bool:
    stmt = select(ConsentRecord).where(ConsentRecord.user_id == uid).limit(1)
    result = await session.execute(stmt)
    return result.scalars().first() is not None


def _parse_date(text: str, *, allow_year_only: bool = False) -> date | None:
    """解析日期文本：ISO、中文年月日、或纯年份（allow_year_only）。"""
    if not text:
        return None
    text = text.strip()
    m = re.match(r"^(\d{4})-(\d{1,2})-(\d{1,2})$", text)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
    m = re.match(r"^(\d{4})年\s*(\d{1,2})月(?:\s*(\d{1,2})日)?$", text)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3) or 1))
        except ValueError:
            return None
    if allow_year_only:
        m = re.match(r"^(\d{4})$", text)
        if m:
            try:
                return date(int(m.group(1)), 1, 1)
            except ValueError:
                return None
    return None


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
