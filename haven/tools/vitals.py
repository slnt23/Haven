"""血压记录工具 —— 确定性校验 + 异常二次确认的两阶段写入。

流程：`record_blood_pressure` 校验并（若需确认）只落待确认行，不写血压表；
`confirm_abnormal_blood_pressure` 校验匹配后消费待确认行并正式入库。
LLM 无法绕开确认：二级及以上异常值没有「确认」就没有行。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from managed_deepagents import ManagedDeepAgentRuntime
from sqlalchemy import select

from application.commands import C_CANCEL, C_CONFIRM
from application.confirmation import LEVEL_CN, check_abnormal, pending_expired
from application.messages import MSG
from application.validation import ValidationLevel, validate_blood_pressure
from storage.database import DatabaseUnavailable, session_scope
from storage.models import PENDING_CONFIRM_TTL, BloodPressure, PendingBpConfirmation
from safety.disclaimers import DisclaimerType, get_disclaimer
from tools._helpers import (
    NO_IDENTITY_REPLY,
    degraded,
    has_consented,
    is_future,
    parse_measured_at,
    uid_of,
)

#: 重复记录窗口（与 src 一致）。
DUPLICATE_WINDOW = timedelta(seconds=60)

_LEVEL_ORDER = list(ValidationLevel)

_CONFIRM_GUIDANCE = (
    f"输入 {C_CONFIRM} 继续保存这条记录；输入 {C_CANCEL} 不保存；"
    "若测量有误或想重新测量，直接告诉我新的血压数值即可。"
)
_PARSE_TIME_ERROR = "测量时间格式无法识别（如 2026-09-01T08:00:00），这条未保存。"
_FUTURE_TIME_ERROR = "测量时间不能晚于当前时间，这条未保存。请确认时间后重新输入。"
_CONFIRM_MISS_REPLY = "未找到可确认的血压记录（记录可能已超过 24 小时或数值不一致），未保存。请重新测量后告诉我最新数值。"
_NO_PENDING_REPLY = "当前没有待确认的血压记录。\n" + MSG.bp_need_value


def _worst_level(
    systolic_level: ValidationLevel, diastolic_level: ValidationLevel
) -> ValidationLevel:
    """显示用分级取两者中更严重者（枚举定义顺序即严重度升序）。"""
    if _LEVEL_ORDER.index(systolic_level) >= _LEVEL_ORDER.index(diastolic_level):
        return systolic_level
    return diastolic_level


async def _find_pending(
    session, uid: str
) -> PendingBpConfirmation | None:
    stmt = (
        select(PendingBpConfirmation)
        .where(PendingBpConfirmation.user_id == uid)
        .limit(1)
    )
    return (await session.execute(stmt)).scalars().first()


async def _recent_duplicate(
    session, uid: str, systolic: int, diastolic: int, measured_at: datetime
) -> bool:
    """同一数值在同一时间窗口（±60 秒）内已有正式记录。"""
    stmt = (
        select(BloodPressure)
        .where(
            BloodPressure.user_id == uid,
            BloodPressure.systolic == systolic,
            BloodPressure.diastolic == diastolic,
            BloodPressure.measured_at >= measured_at - DUPLICATE_WINDOW,
            BloodPressure.measured_at <= measured_at + DUPLICATE_WINDOW,
        )
        .limit(1)
    )
    return (await session.execute(stmt)).scalars().first() is not None


async def record_blood_pressure(
    runtime: ManagedDeepAgentRuntime = None,
    systolic: int | None = None,
    diastolic: int | None = None,
    measured_at: str | None = None,
) -> str:
    """记录一次手动血压测量（如 128/84）。数值须先经过确定性校验；
    二级及以上异常值不会直接保存，转入两阶段确认（见
    `confirm_abnormal_blood_pressure`）。"""
    uid = uid_of(runtime)
    if uid is None:
        return NO_IDENTITY_REPLY
    if systolic is None or diastolic is None:
        return MSG.bp_need_value

    measured = parse_measured_at(measured_at)
    if measured is None:
        return _PARSE_TIME_ERROR
    if is_future(measured):
        return _FUTURE_TIME_ERROR

    validation = validate_blood_pressure(systolic, diastolic)
    if not validation.is_valid:
        return f"{MSG.bp_invalid}：{'；'.join(validation.errors)}。"
    confirm = check_abnormal(systolic, diastolic)

    try:
        async with session_scope() as session:
            if not await has_consented(session, uid):
                return MSG.consent_required
            if await _recent_duplicate(session, uid, systolic, diastolic, measured):
                return f"{systolic}/{diastolic} mmHg 这条在 1 分钟内已记录过，未重复保存。"

            if confirm.needs_confirmation:
                # 两阶段：不落正式记录，只写/刷新待确认行（至多一行）。
                pending = await _find_pending(session, uid)
                now = datetime.now(UTC)
                if pending is None:
                    session.add(
                        PendingBpConfirmation(
                            user_id=uid,
                            systolic=systolic,
                            diastolic=diastolic,
                            measured_at=measured,
                            prompt_text=confirm.message,
                            expires_at=now + PENDING_CONFIRM_TTL,
                        )
                    )
                else:
                    pending.systolic = systolic
                    pending.diastolic = diastolic
                    pending.measured_at = measured
                    pending.prompt_text = confirm.message
                    pending.expires_at = now + PENDING_CONFIRM_TTL
            else:
                session.add(
                    BloodPressure(
                        user_id=uid,
                        systolic=systolic,
                        diastolic=diastolic,
                        measured_at=measured,
                        source="Manual",
                        is_abnormal=validation.is_abnormal,
                        notes=None,
                    )
                )
    except DatabaseUnavailable:
        return degraded()

    if confirm.needs_confirmation:
        return (
            f"{confirm.message}\n"
            f"{MSG.bp_confirm_prompt(systolic, diastolic)}\n"
            f"{_CONFIRM_GUIDANCE}"
        )

    level_cn = LEVEL_CN[
        _worst_level(validation.systolic_level, validation.diastolic_level).value
    ]
    reply = MSG.bp_recorded(systolic, diastolic, level_cn)
    if validation.is_abnormal:
        reply += "\n\n" + get_disclaimer(DisclaimerType.MEDICAL_ADVICE)
    return reply


async def get_pending_blood_pressure(
    runtime: ManagedDeepAgentRuntime = None,
) -> str:
    """查询是否有等待用户确认的异常血压记录（中断后可据此恢复流程）。"""
    uid = uid_of(runtime)
    if uid is None:
        return NO_IDENTITY_REPLY
    try:
        async with session_scope() as session:
            pending = await _find_pending(session, uid)
            if pending is None:
                return _NO_PENDING_REPLY
            if pending_expired(pending.expires_at):
                await session.delete(pending)
                return _NO_PENDING_REPLY
            return f"{pending.prompt_text}\n{_CONFIRM_GUIDANCE}"
    except DatabaseUnavailable:
        return degraded()


async def confirm_abnormal_blood_pressure(
    runtime: ManagedDeepAgentRuntime = None,
    systolic: int | None = None,
    diastolic: int | None = None,
) -> str:
    """保存一条用户已明确「确认」的异常血压。仅当待确认行存在、未过期
    （24 小时）且数值完全一致时才正式入库；否则拒绝且不保存任何数据。"""
    uid = uid_of(runtime)
    if uid is None:
        return NO_IDENTITY_REPLY
    if systolic is None or diastolic is None:
        return _CONFIRM_MISS_REPLY

    validation = validate_blood_pressure(systolic, diastolic)
    try:
        async with session_scope() as session:
            pending = await _find_pending(session, uid)
            if pending is None:
                return _CONFIRM_MISS_REPLY
            if pending_expired(pending.expires_at):
                await session.delete(pending)
                return _CONFIRM_MISS_REPLY
            if not (
                pending.systolic == systolic and pending.diastolic == diastolic
            ):
                return _CONFIRM_MISS_REPLY

            await session.delete(pending)
            session.add(
                BloodPressure(
                    user_id=uid,
                    systolic=systolic,
                    diastolic=diastolic,
                    measured_at=pending.measured_at,
                    source="Manual",
                    is_abnormal=validation.is_abnormal,
                    notes=None,
                )
            )
    except DatabaseUnavailable:
        return degraded()

    reply = MSG.bp_confirmed(systolic, diastolic)
    if validation.is_severe:
        reply += "\n\n该数值属于严重异常范围。如已确认测量无误，请尽快就医。"
    reply += "\n\n" + get_disclaimer(DisclaimerType.MEDICAL_ADVICE)
    return reply
