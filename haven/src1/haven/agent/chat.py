"""Haven Agent 核心 —— 会话管理、意图分发、FSM 流程。

所有用户可见的对话文案优先由 LLM 生成，LLM 不可用时走 MSG 兜底。
安全红线（紧急响应、异常确认、输出过滤）永远走确定性模板。
"""

import re
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from haven.application.confirmation import check_abnormal
from haven.application.consent import get_policy, has_consented, record_consent
from haven.application.emergency import check_emergency
from haven.application.onboarding import (
    DiseaseData,
    ProfileData,
    complete_onboarding,
    get_profile,
)
from haven.application.trends import format_trend_message, get_seven_day_trend
from haven.application.validation import validate_blood_pressure
from haven.application.vitals import BloodPressureData, record_blood_pressure
from haven.domain.models import User
from haven.llm.intent import IntentResult, classify_intent
from haven.llm.response import generate_response
from haven.safety.disclaimers import DisclaimerType, get_disclaimer
from haven.safety.output_filter import filter_output
from haven.safety.state_machine import SafetyContext, SafetyState

from haven.agent.messages import MSG

LEVEL_CN = {
    "normal": "正常",
    "high_normal": "正常高值",
    "grade_1": "1级高血压",
    "grade_2": "2级高血压",
    "grade_3": "3级高血压",
    "severe": "严重异常",
}


# ---------------------------------------------------------------------------
# 会话状态（按用户隔离）
# ---------------------------------------------------------------------------

@dataclass
class OnboardingDraft:
    field_index: int = 0
    gender: str | None = None
    birth_date: date | None = None
    height_cm: float | None = None
    weight_kg: float | None = None
    disease_name: str | None = None
    diagnosed_date: date | None = None


@dataclass
class PendingBp:
    systolic: int
    diastolic: int
    measured_at: datetime


@dataclass
class UserSession:
    safety: SafetyContext = field(default_factory=SafetyContext)
    mode: str = "idle"
    onboarding: OnboardingDraft | None = None
    pending_bp: PendingBp | None = None


_sessions: dict[UUID, UserSession] = {}


def _get_session(user_id: UUID) -> UserSession:
    session = _sessions.get(user_id)
    if session is None:
        session = UserSession()
        _sessions[user_id] = session
    return session


# ---------------------------------------------------------------------------
# 通用解析
# ---------------------------------------------------------------------------

def _parse_bp(text: str) -> tuple[int, int] | None:
    patterns = [
        r"(\d{2,3})\s*[\/／]\s*(\d{2,3})",
        r"收缩压\s*(\d{2,3}).*?舒张压\s*(\d{2,3})",
        r"高压\s*(\d{2,3}).*?低压\s*(\d{2,3})",
        r"血压\D*(\d{2,3})\D+(\d{2,3})",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            systolic = int(match.group(1))
            diastolic = int(match.group(2))
            if 60 <= systolic <= 300 and 30 <= diastolic <= 200:
                return systolic, diastolic
    return None


_INTENT_KEYWORDS: dict[str, list[str]] = {
    "record_blood_pressure": ["血压", "收缩压", "舒张压", "高压", "低压", "量了"],
    "view_trend": ["趋势", "最近", "一周", "七天", "统计"],
    "give_consent": ["隐私", "同意", "政策", "免责"],
    "create_profile": ["建档", "个人资料", "基本信息", "资料"],
    "greeting": ["你好", "嗨", "hello", "hi", "您好", "你是谁", "介绍", "叫什么", "名字"],
    "ask_help": ["帮助", "功能", "能做什么", "可以做什么", "怎么用"],
}


def _keyword_intent(text: str) -> IntentResult:
    bp_values = _parse_bp(text)
    has_trend = any(w in text for w in _INTENT_KEYWORDS["view_trend"])
    if bp_values and not has_trend:
        return IntentResult(
            intent="record_blood_pressure",
            params={"systolic": bp_values[0], "diastolic": bp_values[1]},
            confidence=0.9,
        )
    if any(w in text for w in _INTENT_KEYWORDS["record_blood_pressure"]):
        if has_trend:
            return IntentResult(intent="view_trend", confidence=0.9)
        if bp_values:
            return IntentResult(
                intent="record_blood_pressure",
                params={"systolic": bp_values[0], "diastolic": bp_values[1]},
                confidence=0.9,
            )
        return IntentResult(intent="record_blood_pressure", confidence=0.5)

    for intent, words in _INTENT_KEYWORDS.items():
        if intent in {"record_blood_pressure", "view_trend"}:
            continue
        if any(w in text for w in words):
            return IntentResult(intent=intent, confidence=0.9)
    return IntentResult(intent="general_question", confidence=0.3)


_AFFIRM_WORDS = ("确认", "确定", "对的", "是的", "是", "对", "无误", "没错", "可以", "就这样", "嗯")
_DENY_WORDS = ("取消", "不了", "不对", "不是", "错了", "不要", "没有", "重新", "重测", "算了", "放弃", "改")


def _is_deny(text: str) -> bool:
    return any(word in text for word in _DENY_WORDS)


def _is_affirm(text: str) -> bool:
    return any(word in text for word in _AFFIRM_WORDS)


# ---------------------------------------------------------------------------
# 建档 FSM
# ---------------------------------------------------------------------------

_SKIP_WORDS = ("跳过", "不填", "没有", "暂无", "无", "算了", "不想填")

ONBOARDING_FIELDS = (
    "gender",
    "birth_date",
    "height_cm",
    "weight_kg",
    "disease_name",
    "diagnosed_date",
)

FIELD_PROMPTS = {
    "gender": "您的性别是？（回复：男 / 女）",
    "birth_date": "您的出生日期是？（如 1950-03-12，也可写 1950年3月12日）",
    "height_cm": "您的身高是多少厘米？（如 165；回复「跳过」可不填）",
    "weight_kg": "您的体重是多少公斤？（如 65；回复「跳过」可不填）",
    "disease_name": "您确诊的慢病名称是？（0.0.1 版可登记：高血压）",
    "diagnosed_date": "高血压大约何时确诊？（如 2020 或 2020-05；回复「跳过」则记为今天）",
}


def _is_skip(text: str) -> bool:
    return any(word in text for word in _SKIP_WORDS)


def _extract_year_month_day(text: str) -> date | None:
    today = date.today()
    m = re.search(r"(19|20)\d{2}", text)
    if not m:
        return None
    year = int(m.group(0))
    if not (1900 <= year <= today.year):
        return None
    month = day = 1
    m2 = re.search(r"(\d{1,2})\s*月(?:\s*(\d{1,2})\s*日)?", text)
    m3 = re.search(r"[-/.]\s*(\d{1,2})\s*[-/.]\s*(\d{1,2})", text)
    if m2:
        month = int(m2.group(1))
        day = int(m2.group(2)) if m2.group(2) else 1
    elif m3:
        month = int(m3.group(1))
        day = int(m3.group(2))
    try:
        parsed = date(year, month, day)
    except ValueError:
        return None
    if parsed > today:
        return None
    return parsed


def _extract_number(text: str, lo: float, hi: float) -> float | None:
    for m in re.finditer(r"\d{1,4}", text):
        value = float(m.group(0))
        if lo <= value <= hi:
            return value
    return None


def _parse_field_value(field: str, text: str):
    if field == "gender":
        if "女" in text:
            return "女", True
        if "男" in text:
            return "男", True
        return None, False
    if field == "birth_date":
        value = _extract_year_month_day(text)
        return value, value is not None
    if field == "height_cm":
        if _is_skip(text):
            return None, True
        value = _extract_number(text, 80, 250)
        return value, value is not None
    if field == "weight_kg":
        if _is_skip(text):
            return None, True
        value = _extract_number(text, 2, 500)
        return value, value is not None
    if field == "disease_name":
        cleaned = re.sub(r"[，。,\s]+", "", text)
        if not cleaned:
            return None, False
        return ("高血压" if "高血压" in cleaned else cleaned), True
    if field == "diagnosed_date":
        if _is_skip(text):
            return None, True
        value = _extract_year_month_day(text)
        return value, value is not None
    return None, False


def _current_field(draft: OnboardingDraft) -> str:
    return ONBOARDING_FIELDS[draft.field_index]


def _next_onboarding_prompt(draft: OnboardingDraft) -> str:
    return FIELD_PROMPTS[_current_field(draft)]


def _onboarding_summary(d: OnboardingDraft) -> str:
    disease_date = d.diagnosed_date.isoformat() if d.diagnosed_date else "今天"
    lines = [
        "我将为您创建健康档案：",
        f"· 性别：{d.gender or '未填'}",
        f"· 出生日期：{d.birth_date.isoformat() if d.birth_date else '未填'}",
        f"· 身高：{int(d.height_cm)} cm" if d.height_cm else "· 身高：未填",
        f"· 体重：{int(d.weight_kg)} kg" if d.weight_kg else "· 体重：未填",
        f"· 确诊慢病：{d.disease_name or '高血压'}（确诊：{disease_date}）",
        "",
        "确认无误请回复「确认」；要修改请说明（如「身高170」「出生1960-01-01」）。",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 同意校验
# ---------------------------------------------------------------------------

async def _consent_required(session: AsyncSession, user_id: UUID) -> str | None:
    if await has_consented(session, user_id):
        return None
    return await generate_response("consent", action="required") or MSG.consent_required


async def _ensure_user(session: AsyncSession, user_id: UUID) -> None:
    stmt = select(User).where(User.user_id == user_id)
    result = await session.execute(stmt)
    user = result.scalar_one_or_none()
    if user is None:
        user = User(
            user_id=user_id,
            username=f"user_{user_id.hex[:8]}",
            password_hash="mpv_placeholder",
            nickname="用户",
        )
        session.add(user)
        await session.commit()


# ---------------------------------------------------------------------------
# 建档保存
# ---------------------------------------------------------------------------

async def _save_onboarding(session: AsyncSession, user_id: UUID, d: OnboardingDraft) -> str:
    profile = await get_profile(session, user_id)
    
    profile_data = ProfileData(
        gender=d.gender or "未知",
        birth_date=d.birth_date or date(1970, 1, 1),
        height_cm=d.height_cm,
        weight_kg=d.weight_kg,
    )
    disease = DiseaseData(
        disease_name=d.disease_name or "高血压",
        diagnosed_date=d.diagnosed_date or date.today(),
    )
    
    if profile is None:
        await complete_onboarding(session, user_id, profile_data, diseases=[disease])
    else:
        from haven.application.onboarding import update_profile, add_disease
        await update_profile(session, user_id, profile_data)
        await add_disease(session, user_id, disease)

    return await generate_response(
        "onboarding", action="done",
        gender=profile_data.gender,
        birth_date=profile_data.birth_date.isoformat(),
        disease_name=disease.disease_name,
    ) or MSG.onboarding_done(profile_data.gender, profile_data.birth_date.isoformat(), disease.disease_name)


# ---------------------------------------------------------------------------
# 建档 FSM 步骤
# ---------------------------------------------------------------------------

async def _start_onboarding(session: AsyncSession, user_id: UUID) -> str:
    consent_text = await _consent_required(session, user_id)
    if consent_text:
        return consent_text

    _get_session(user_id).mode = "onboarding"
    _get_session(user_id).onboarding = OnboardingDraft()
    field = FIELD_PROMPTS["gender"]

    return await generate_response("onboarding", action="start", field_name="gender", field_prompt=field) \
        or MSG.onboarding_start(field)


async def _onboarding_step(us: UserSession, text: str) -> str:
    draft = us.onboarding
    if draft is None:
        us.mode = "idle"
        return MSG.onboarding_interrupted

    field = _current_field(draft)
    value, ok = _parse_field_value(field, text)
    if not ok:
        prompt = FIELD_PROMPTS[field]
        return await generate_response("onboarding", action="parse_error", field_name=field, field_prompt=prompt) \
            or MSG.onboarding_parse_error(field, prompt)

    setattr(draft, field, value)

    if draft.field_index + 1 >= len(ONBOARDING_FIELDS):
        us.mode = "onboarding_confirm"
        summary = _onboarding_summary(draft)
        return await generate_response("onboarding", action="summary", summary_data=summary) or summary

    draft.field_index += 1
    prompt = _next_onboarding_prompt(draft)
    return await generate_response("onboarding", action="ask", field_name=_current_field(draft), field_prompt=prompt) \
        or prompt


async def _onboarding_confirm_step(
    us: UserSession, text: str, session: AsyncSession, user_id: UUID
) -> str:
    draft = us.onboarding
    if draft is None:
        us.mode = "idle"
        return MSG.onboarding_interrupted

    if _is_deny(text):
        us.mode = "idle"
        us.onboarding = None
        return await generate_response("onboarding", action="cancel") or MSG.onboarding_cancelled

    if _is_affirm(text):
        reply = await _save_onboarding(session, user_id, draft)
        us.mode = "idle"
        us.onboarding = None
        return reply

    changed = False
    if "男" in text or "女" in text:
        value, ok = _parse_field_value("gender", text)
        if ok and value and value != draft.gender:
            draft.gender = value
            changed = True
    if any(k in text for k in ("出生", "生日")) or re.search(r"(19|20)\d{2}", text):
        value, ok = _parse_field_value("birth_date", text)
        if ok and value:
            draft.birth_date = value
            changed = True
    if any(k in text for k in ("身高", "高")) and _extract_number(text, 80, 250) is not None:
        value, ok = _parse_field_value("height_cm", text)
        if ok and value is not None:
            draft.height_cm = value
            changed = True
    if any(k in text for k in ("体重", "重", "kg", "公斤")) and _extract_number(text, 2, 500) is not None:
        value, ok = _parse_field_value("weight_kg", text)
        if ok and value is not None:
            draft.weight_kg = value
            changed = True
    if "疾病" in text or "高血压" in text:
        value, ok = _parse_field_value("disease_name", text)
        if ok and value:
            draft.disease_name = value
            changed = True
    if "确诊" in text:
        value, ok = _parse_field_value("diagnosed_date", text)
        if ok:
            draft.diagnosed_date = value or date.today()
            changed = True

    if changed:
        summary = _onboarding_summary(draft)
        return await generate_response("onboarding", action="summary", summary_data=summary) or summary
    return MSG.onboarding_confirm_prompt


# ---------------------------------------------------------------------------
# 血压记录
# ---------------------------------------------------------------------------

async def _try_record_bp(
    us: UserSession, systolic: int, diastolic: int, session: AsyncSession, user_id: UUID
) -> str:
    validation = validate_blood_pressure(systolic, diastolic)
    if not validation.is_valid:
        return validation.errors[0] if validation.errors else MSG.bp_invalid

    consent_text = await _consent_required(session, user_id)
    if consent_text:
        return consent_text

    confirmation = check_abnormal(systolic, diastolic)
    if confirmation.needs_confirmation:
        us.mode = "bp_confirm"
        us.pending_bp = PendingBp(systolic=systolic, diastolic=diastolic, measured_at=datetime.now(UTC))
        return confirmation.message

    await record_blood_pressure(session, user_id, BloodPressureData(systolic=systolic, diastolic=diastolic))
    level_cn = LEVEL_CN.get(validation.systolic_level.value, "")

    return await generate_response(
        "bp_record", action="record_ok", systolic=systolic, diastolic=diastolic, level=level_cn
    ) or MSG.bp_recorded(systolic, diastolic, level_cn)


async def _bp_confirm_step(
    us: UserSession, text: str, session: AsyncSession, user_id: UUID
) -> str:
    pending = us.pending_bp
    if pending is None:
        us.mode = "idle"
        return await _handle_idle(us, text, session, user_id)

    if _is_deny(text):
        us.mode = "idle"
        us.pending_bp = None
        return await generate_response("bp_record", action="cancel") or MSG.bp_cancelled

    if _is_affirm(text):
        await record_blood_pressure(session, user_id, BloodPressureData(
            systolic=pending.systolic, diastolic=pending.diastolic, measured_at=pending.measured_at,
        ))
        us.mode = "idle"
        us.pending_bp = None
        return await generate_response(
            "bp_record", action="confirm_ok", systolic=pending.systolic, diastolic=pending.diastolic,
        ) or MSG.bp_confirmed(pending.systolic, pending.diastolic)

    bp = _parse_bp(text)
    if bp:
        return await _try_record_bp(us, bp[0], bp[1], session, user_id)

    return await generate_response(
        "bp_record", action="confirm_prompt", systolic=pending.systolic, diastolic=pending.diastolic,
    ) or MSG.bp_confirm_prompt(pending.systolic, pending.diastolic)


# ---------------------------------------------------------------------------
# idle 意图分发
# ---------------------------------------------------------------------------

async def _handle_consent(text: str, session: AsyncSession, user_id: UUID) -> str:
    if "同意" in text or "接受" in text:
        if await has_consented(session, user_id):
            return await generate_response("consent", action="already") or MSG.consent_already
        await record_consent(session, user_id, "0.0.1")
        return await generate_response("consent", action="granted") or MSG.consent_granted
    return await get_policy()


async def _handle_trend(session: AsyncSession, user_id: UUID) -> str:
    return format_trend_message(await get_seven_day_trend(session, user_id))


async def _handle_idle(us: UserSession, text: str, session: AsyncSession, user_id: UUID) -> str:
    intent = await classify_intent(text)
    if intent.intent == "unavailable":
        intent = _keyword_intent(text)

    if intent.intent == "record_blood_pressure":
        systolic = intent.params.get("systolic")
        diastolic = intent.params.get("diastolic")
        if systolic is not None and diastolic is not None:
            return await _try_record_bp(us, int(systolic), int(diastolic), session, user_id)
        bp = _parse_bp(text)
        if bp:
            return await _try_record_bp(us, bp[0], bp[1], session, user_id)
        return await generate_response("idle", action="need_bp_value") or MSG.bp_need_value

    if intent.intent == "view_trend":
        return await _handle_trend(session, user_id)

    if intent.intent == "create_profile":
        return await _start_onboarding(session, user_id)

    if intent.intent == "give_consent":
        return await _handle_consent(text, session, user_id)

    if intent.intent == "greeting":
        return await generate_response("greeting", text) or MSG.greeting

    if intent.intent == "ask_help":
        return await generate_response("ask_help", text) or MSG.ask_help

    return await generate_response("general_question", text) or get_disclaimer(DisclaimerType.KNOWLEDGE_QA)


# ---------------------------------------------------------------------------
# 对外入口
# ---------------------------------------------------------------------------

async def handle_message(text: str, session: AsyncSession, user_id: UUID) -> dict:
    if not text:
        reply = await generate_response("idle", action="empty_input") or MSG.empty_input
        return {"reply": reply, "is_emergency": False}

    await _ensure_user(session, user_id)
    us = _get_session(user_id)

    emergency = check_emergency(text)
    if emergency.is_emergency:
        us.safety.transition_to(SafetyState.EMERGENCY)
        reply = filter_output(emergency.response)
        us.safety.transition_to(SafetyState.NORMAL)
        return {"reply": reply, "is_emergency": True}

    if us.safety.state == SafetyState.EMERGENCY:
        us.safety.transition_to(SafetyState.NORMAL)

    try:
        if us.mode == "onboarding":
            reply = await _onboarding_step(us, text)
        elif us.mode == "onboarding_confirm":
            reply = await _onboarding_confirm_step(us, text, session, user_id)
        elif us.mode == "bp_confirm":
            reply = await _bp_confirm_step(us, text, session, user_id)
        else:
            reply = await _handle_idle(us, text, session, user_id)
    except Exception:
        reply = await generate_response("error") or MSG.error_fallback

    return {"reply": filter_output(reply), "is_emergency": False}