"""健康建档工具（0.0.1：高血压）。

字段词表、状态机与逐字段校验集中在 `application/onboarding.py` ——
**建档草稿（保存中）与正式建档（保存时）共用同一套规则**，不会两处判出
不同结果。建档即整档重写：删除旧健康问题记录后写一条当前记录
（避免重复行累积）。

续接（B3）：用户每答一项，模型调 `save_onboarding_draft` 落一行草稿
（`onboarding_drafts`，user_id 主键），换线程/换会话后由记忆注入读出，
从 `next_field` 接着问，不必重头再来。
"""

from __future__ import annotations

from datetime import UTC, date, datetime

from managed_deepagents import ManagedDeepAgentRuntime
from sqlalchemy import delete, select

from application.commands import C_PROFILE
from application.messages import MSG
from application.onboarding import (
    STEP_LABELS,
    STEP_ORDER,
    SUPPORTED_DISEASE,
    clean_value,
    fmt_num,
    next_step,
    validate_step,
)
from storage.database import DatabaseUnavailable, session_scope
from storage.models import DiseaseRecord, HealthProfile, OnboardingDraft
from tools._helpers import NO_IDENTITY_REPLY, degraded, has_consented, uid_of


async def get_health_profile(runtime: ManagedDeepAgentRuntime = None) -> str:
    """读取当前用户的健康档案与登记的健康问题（须已同意隐私政策）。"""
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
                return f"您还没有健康档案。输入 {C_PROFILE}，我来帮您创建。"
            diseases = (
                await session.execute(
                    select(DiseaseRecord).where(DiseaseRecord.user_id == uid)
                )
            ).scalars().all()
    except DatabaseUnavailable:
        return degraded()

    lines = ["您的健康档案："]
    if profile.nickname:
        lines.append(f"· 称呼：{profile.nickname}")
    lines += [
        f"· 性别：{profile.gender}",
        f"· 出生日期：{profile.birth_date.isoformat()}",
    ]
    if profile.height_cm is not None:
        lines.append(f"· 身高：{fmt_num(profile.height_cm)} 厘米")
    if profile.weight_kg is not None:
        lines.append(f"· 体重：{fmt_num(profile.weight_kg)} 公斤")
    for disease in diseases:
        lines.append(
            f"· 健康问题：{disease.disease_name}（确诊于 {disease.diagnosed_date.isoformat()}）"
        )
    lines.append(f"如需更新，输入 {C_PROFILE} 重新填写。")
    return "\n".join(lines)


async def save_health_profile(
    runtime: ManagedDeepAgentRuntime = None,
    nickname: str | None = None,
    gender: str | None = None,
    birth_date: str | None = None,
    height_cm: float | None = None,
    weight_kg: float | None = None,
    disease_name: str = SUPPORTED_DISEASE,
    diagnosed_date: str | None = None,
) -> str:
    """保存（或更新）健康档案。须先获得用户同意的隐私政策，
    且用户已确认建档摘要后调用。0.0.1 仅支持登记高血压。

    成功时在**同一事务内**删除该用户的建档草稿 —— 档案已是权威数据，
    草稿再留着只会让记忆注入报出"未完的建档进度"。

    **整档重写语义**：省略某个可跳过项（`nickname`/`height_cm`/`weight_kg`/
    `diagnosed_date`）等于把它清空，与「跳过即不填」一致；不搞"None 表示不改"
    的隐藏规则 —— 那会让一个字段和其它六个行为不一致。代价由确认前的
    **复述摘要**兜住（用户能看到「· 称呼：… / 未填」）。
    """
    uid = uid_of(runtime)
    if uid is None:
        return NO_IDENTITY_REPLY

    # ── 确定性校验（与建档草稿共用同一套规则，不依赖 LLM） ──
    # 校验通过即保证：gender/birth/disease 非 None；其余可跳过项可为 None。
    name, error = validate_step("nickname", nickname)
    if error is not None:
        return error
    gender_value, error = validate_step("gender", gender)
    if error is not None:
        return error
    birth, error = validate_step("birth_date", birth_date)
    if error is not None:
        return error
    height, error = validate_step("height_cm", height_cm)
    if error is not None:
        return error
    weight, error = validate_step("weight_kg", weight_kg)
    if error is not None:
        return error
    disease, error = validate_step("disease_name", disease_name or SUPPORTED_DISEASE)
    if error is not None:
        return error
    diagnosed, error = validate_step("diagnosed_date", diagnosed_date)
    if error is not None:
        return error
    if diagnosed is None:  # 可跳过项：默认今天
        diagnosed = date.today()

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
                        nickname=name,
                        gender=gender_value,
                        birth_date=birth,
                        height_cm=height,
                        weight_kg=weight,
                    )
                )
            else:
                profile.nickname = name
                profile.gender = gender_value
                profile.birth_date = birth
                profile.height_cm = height
                profile.weight_kg = weight
                profile.updated_at = datetime.now(UTC)
            # 0.0.1 单一健康问题：整档重写，删除旧记录避免重复行。
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
            # 档案落定，草稿使命结束（同一事务内）
            await session.execute(
                delete(OnboardingDraft).where(OnboardingDraft.user_id == uid)
            )
    except DatabaseUnavailable:
        return degraded()
    return MSG.onboarding_done(name, gender_value, birth.isoformat(), disease)


async def save_onboarding_draft(
    runtime: ManagedDeepAgentRuntime = None,
    step: str | None = None,
    value: str | None = None,
) -> str:
    """记录建档进度（**内部记账**，模型不应把返回值转达给用户）。

    用户每提供一项后由模型调用，使建档成为可跨线程/跨会话续接的对话状态流
    （B3）。`step` 是封闭词表（见 `application.onboarding.STEP_ORDER`）——
    模型不能自由发挥，否则 `next_field` 游标会失效。`value` 留空表示跳过，
    仅对可跳过项（身高 / 体重 / 确诊时间）合法。

    写入的是出生日期、身高、体重、确诊时间等健康数据，因此与其它写入路径
    一样设同意闸门（REQ-005 §4.3：撤回同意后采集入口必须在服务端拒绝写入）。
    """
    uid = uid_of(runtime)
    if uid is None:
        return NO_IDENTITY_REPLY
    if step not in STEP_ORDER:
        return (
            f"（内部）未知的建档项「{clean_value(step)}」。"
            f"合法取值：{'、'.join(STEP_ORDER)}。"
        )

    parsed, error = validate_step(step, value)
    if error is not None:
        return error

    try:
        async with session_scope() as session:
            if not await has_consented(session, uid):
                return MSG.consent_required
            stmt = select(OnboardingDraft).where(OnboardingDraft.user_id == uid).limit(1)
            draft = (await session.execute(stmt)).scalars().first()
            if draft is None:
                # 同一用户的建档是逐项问答，天然串行；并发同 step 的 PK 冲突
                # 概率可忽略，且失败只会降级为一次固定文案，不丢已有进度。
                draft = OnboardingDraft(user_id=uid)
                session.add(draft)
            setattr(draft, step, parsed)  # parsed 为 None 即"该项跳过"
            draft.next_field = next_step(step)
            draft.updated_at = datetime.now(UTC)
    except DatabaseUnavailable:
        return degraded()

    upcoming = next_step(step)
    tail = (
        f"下一项：{STEP_LABELS[upcoming]}"
        if upcoming is not None
        else f"{len(STEP_ORDER)} 项已收集齐，等待用户确认"
    )
    return (
        f"（内部记录，不要向用户转达本条）{STEP_LABELS[step]} 进度已保存；{tail}。"
    )
