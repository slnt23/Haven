"""隐私同意工具 —— 0.0.1 一切健康数据操作之前的闸门。

同意为一次性（同调用者重复同意不落重复行、不重复审计）。
"""

from __future__ import annotations

from managed_deepagents import ManagedDeepAgentRuntime
from sqlalchemy import select

from application.messages import MSG
from db.audit import record_audit, subject_key_for
from db.database import DatabaseUnavailable, session_scope
from db.models import ConsentRecord
from safety.disclaimers import DisclaimerType, get_disclaimer
from tools._helpers import NO_IDENTITY_REPLY, degraded, uid_of

POLICY_VERSION = "0.0.1"
#: 与 src 的 consent scope 保持一致。
SCOPE = "health_data_collection"

_AGREE_GUIDANCE = "\n\n如您同意以上内容，请回复「同意隐私政策」以继续。"


def get_consent_policy() -> str:
    """展示隐私政策全文。首次使用必须先同意，之后才能建档与记录健康数据。"""
    return get_disclaimer(DisclaimerType.FIRST_USE) + _AGREE_GUIDANCE


async def consent_status(runtime: ManagedDeepAgentRuntime = None) -> str:
    """查询当前用户的隐私同意状态；未同意时返回政策全文与同意指引。"""
    uid = uid_of(runtime)
    if uid is None:
        return NO_IDENTITY_REPLY
    try:
        async with session_scope() as session:
            stmt = select(ConsentRecord).where(ConsentRecord.user_id == uid).limit(1)
            result = await session.execute(stmt)
            consented = result.scalars().first() is not None
    except DatabaseUnavailable:
        return degraded()
    if consented:
        return MSG.consent_already
    return get_disclaimer(DisclaimerType.FIRST_USE) + _AGREE_GUIDANCE


async def record_consent(runtime: ManagedDeepAgentRuntime = None) -> str:
    """记录当前用户的隐私同意（政策版本 0.0.1）。仅在用户明确表示同意后调用。"""
    uid = uid_of(runtime)
    if uid is None:
        return NO_IDENTITY_REPLY
    try:
        async with session_scope() as session:
            stmt = select(ConsentRecord).where(ConsentRecord.user_id == uid).limit(1)
            result = await session.execute(stmt)
            if result.scalars().first() is not None:
                return MSG.consent_already
            session.add(
                ConsentRecord(
                    user_id=uid,
                    policy_version=POLICY_VERSION,
                    scope=SCOPE,
                )
            )
            await record_audit(
                session,
                subject_key=subject_key_for(uid),
                event_type="consent",
                event_summary="consent:granted",
            )
    except DatabaseUnavailable:
        return degraded()
    return MSG.consent_granted
