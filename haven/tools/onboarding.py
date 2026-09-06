"""健康建档工具（0.0.1：高血压）。

确定性校验规则与提示取自 src（性别枚举 / 出生 1900–今天 / 身高 80–250
厘米 / 体重 2–500 公斤 / 疾病仅支持 高血压）。建档即整档重写：
删除旧慢病记录后写一条当前疾病（避免重复行累积）。
"""

from __future__ import annotations

from datetime import UTC, date, datetime

from managed_deepagents import ManagedDeepAgentRuntime
from sqlalchemy import delete, select

from application.messages import MSG
from db.database import DatabaseUnavailable, session_scope
from db.models import BloodPressure, DiseaseRecord, HealthProfile
from tools._helpers import _parse_date, degraded, has_consented, uid_of

GENDERS = ("男", "女")
BIRTH_MIN = date(1900, 1, 1)
HEIGHT_MIN, HEIGHT_MAX = 80, 250
WEIGHT_MIN, WEIGHT_MAX = 2, 500
SUPPORTED_DISEASE = "高血压"


def _fmt_num(value: float) -> str:
    """170.0 -> 170；170.5 原样。"""
    return f"{value:.0f}" if float(value).is_integer() else f"{value}"


async def get_health_profile(runtime: ManagedDeepAgentRuntime = None) -> str:
    """读取当前用户的健康档案与慢病信息（须已同意隐私政策）。"""
    uid = uid_of(runtime)
    if uid is None:
        return NO_IDENTITY_REPLY
    try:
        async with session_scope() as session:
            if not await has_consented(session, uid):
                return MSG.consent_required
            stmt = select(HealthProfile).where(HealthProfile.user_id == uid).limit(1)
            profile = (await session.execute(stmt)).scalars().first()
            if profile is None:
                return "您还没有健康档案。回复「建档」，我来帮您创建。"
            diseases = (
                await session.execute(
                    select(DiseaseRecord).where(DiseaseRecord.user_id == uid)
                )
            ).scalars().all()
    except DatabaseUnavailable:
        return degraded()

    lines = [
        "您的健康档案：",
        f"· 性别：{profile.gender}",
        f"· 出生日期：{profile.birth_date.isoformat()}",
    ]
    if profile.height_cm is not None:
        lines.append(f"· 身高：{_fmt_num(profile.height_cm)} 厘米")
    if profile.weight_kg is not None:
        lines.append(f"· 体重：{_fmt_num(profile.weight_kg)} 公斤")
    for disease in diseases:
        lines.append(
            f"· 确诊慢病：{disease.disease_name}（确诊于 {disease.diagnosed_date.isoformat()}）"
        )
    lines.append("如需更新，回复「建档」重新填写。")
    return "\n".join(lines)


async def save_health_profile(
    runtime: ManagedDeepAgentRuntime = None,
    gender: str | None = None,
    birth_date: str | None = None,
    height_cm: float | None = None,
    weight_kg: float | None = None,
    disease_name: str = SUPPORTED_DISEASE,
    diagnosed_date: str | None = None,
) -> str:
    """保存（或更新）健康档案。须先获得用户同意的隐私政策，
    且用户已确认建档摘要后调用。0.0.1 仅支持登记高血压。"""
    uid = uid_of(runtime)
    if uid is None:
        return NO_IDENTITY_REPLY

    # ── 确定性校验（不依赖 LLM） ──
    if gender not in GENDERS:
        return f"性别只能填写「男」或「女」，收到「{gender}」。请确认后重试。"
    birth = _parse_date(birth_date or "", allow_year_only=True)
    if birth is None or birth < BIRTH_MIN or birth > date.today():
        return f"出生日期需在 1900-01-01 到今天的范围内，收到「{birth_date}」。请按 1950-03-12 的格式重试。"
    if height_cm is not None and not (HEIGHT_MIN <= height_cm <= HEIGHT_MAX):
        return f"身高需在 {HEIGHT_MIN}-{HEIGHT_MAX} 厘米之间，收到 {height_cm}。请确认后重试。"
    if weight_kg is not None and not (WEIGHT_MIN <= weight_kg <= WEIGHT_MAX):
        return f"体重需在 {WEIGHT_MIN}-{WEIGHT_MAX} 公斤之间，收到 {weight_kg}。请确认后重试。"
    disease = (disease_name or SUPPORTED_DISEASE).strip()
    if disease != SUPPORTED_DISEASE:
        return "0.0.1 版本仅支持登记高血压。"
    if diagnosed_date is None:
        diagnosed = date.today()
    else:
        diagnosed = _parse_date(diagnosed_date, allow_year_only=True)
        if diagnosed is None:
            return f"确诊时间无法识别（收到「{diagnosed_date}」，示例 2020-05 或 2020-05-01），请重试。"
        if diagnosed > date.today():
            return f"确诊时间不能晚于今天（收到 {diagnosed.isoformat()}），请确认后重试。"

    try:
        async with session_scope() as session:
            if not await has_consented(session, uid):
                return MSG.consent_required
            stmt = select(HealthProfile).where(HealthProfile.user_id == uid).limit(1)
            profile = (await session.execute(stmt)).scalars().first()
            if profile is None:
                session.add(
                    HealthProfile(
                        user_id=uid,
                        gender=gender,
                        birth_date=birth,
                        height_cm=height_cm,
                        weight_kg=weight_kg,
                    )
                )
            else:
                profile.gender = gender
                profile.birth_date = birth
                profile.height_cm = height_cm
                profile.weight_kg = weight_kg
                profile.updated_at = datetime.now(UTC)
            # 0.0.1 单一慢病：整档重写，删除旧记录避免重复行。
            await session.execute(
                delete(DiseaseRecord).where(DiseaseRecord.user_id == uid)
            )
            session.add(
                DiseaseRecord(
                    user_id=uid,
                    disease_name=disease,
                    diagnosed_date=diagnosed,
                    severity=None,
                    status="Active",
                    notes=None,
                )
            )
    except DatabaseUnavailable:
        return degraded()
    return MSG.onboarding_done(gender, birth.isoformat(), disease)
