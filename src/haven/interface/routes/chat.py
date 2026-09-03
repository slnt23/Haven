import re
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from haven.application.confirmation import check_abnormal
from haven.application.consent import get_policy
from haven.application.emergency import check_emergency
from haven.application.trends import format_trend_message, get_seven_day_trend
from haven.application.validation import validate_blood_pressure
from haven.application.vitals import BloodPressureData, record_blood_pressure
from haven.domain.models import User
from haven.interface.deps import get_current_user_id, get_db
from haven.llm.intent import IntentResult, classify_intent
from haven.llm.response import generate_response
from haven.safety.disclaimers import DisclaimerType, get_disclaimer
from haven.safety.output_filter import filter_output
from haven.safety.state_machine import SafetyContext, SafetyState

router = APIRouter(prefix="/api/chat", tags=["chat"])

# 按用户隔离的安全状态机（主路线 B4：禁止模块级全局单例跨用户共享状态）。
_safety_states: dict[UUID, SafetyContext] = {}


def _get_safety(user_id: UUID) -> SafetyContext:
    context = _safety_states.get(user_id)
    if context is None:
        context = SafetyContext()
        _safety_states[user_id] = context
    return context


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


class ChatRequest(BaseModel):
    message: str


class ChatResponse(BaseModel):
    reply: str
    is_emergency: bool = False


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


async def _handle_blood_pressure(
    text: str,
    session: AsyncSession,
    user_id: UUID,
) -> str:
    bp = _parse_bp(text)
    if bp is None:
        return "请告诉我您的血压值，例如：120/80"

    systolic, diastolic = bp

    validation = validate_blood_pressure(systolic, diastolic)
    if not validation.is_valid:
        return validation.errors[0] if validation.errors else "血压数值不合法，请重新输入"

    confirmation = check_abnormal(systolic, diastolic)
    if confirmation.needs_confirmation:
        return confirmation.message

    await record_blood_pressure(
        session,
        user_id,
        BloodPressureData(systolic=systolic, diastolic=diastolic),
    )

    level = validation.systolic_level.value
    return f"已记录血压 {systolic}/{diastolic} mmHg（{level}）。继续保持监测！"


async def _handle_trend(
    session: AsyncSession,
    user_id: UUID,
) -> str:
    summary = await get_seven_day_trend(session, user_id)
    return format_trend_message(summary)


async def _handle_consent(
    text: str,
    session: AsyncSession,
    user_id: UUID,
) -> str:
    from haven.application.consent import has_consented, record_consent

    if any(word in text for word in ["同意", "接受", "确认", "知道", "了解"]):
        already = await has_consented(session, user_id)
        if already:
            return "您已同意过隐私政策，无需重复操作。"
        await record_consent(session, user_id, "0.0.1")
        return "感谢您的同意！现在您可以开始使用 Haven 的各项功能了。您可以先建档，或者直接记录血压。"
    return await get_policy()


async def _handle_onboarding(
    session: AsyncSession,
    user_id: UUID,
) -> str:
    from haven.application.onboarding import get_profile

    profile = await get_profile(session, user_id)
    if profile is not None:
        return "您已经完成建档。如需修改，请告诉我您的性别、出生日期、身高体重等信息。"
    return "请告诉我您的基本信息：性别、出生日期（如 1990-01-01）、身高（cm）、体重（kg），我来帮您建档。"


@router.post("", response_model=ChatResponse)
async def chat(
    body: ChatRequest,
    request: Request,
    session: AsyncSession = Depends(get_db),
    user_id: UUID = Depends(get_current_user_id),
) -> ChatResponse:
    text = body.message.strip()
    if not text:
        return ChatResponse(reply="请告诉我您的需求，我会尽力帮助您。")

    await _ensure_user(session, user_id)
    ctx = _get_safety(user_id)

    emergency = check_emergency(text)
    if emergency.is_emergency:
        ctx.transition_to(SafetyState.EMERGENCY)
        reply = filter_output(emergency.response)
        ctx.transition_to(SafetyState.NORMAL)
        return ChatResponse(reply=reply, is_emergency=True)

    if ctx.state == SafetyState.EMERGENCY:
        ctx.transition_to(SafetyState.NORMAL)

    try:
        intent = await classify_intent(text)
        if intent.intent == "unavailable":
            intent = _keyword_intent(text)

        reply = await _dispatch_intent(intent, text, session, user_id)
        reply = await generate_response(text, reply)
    except Exception:
        reply = (
            "抱歉，我暂时无法处理您的请求，请稍后再试。"
            "如有紧急情况，请立即拨打 120。"
        )

    reply = filter_output(reply)
    return ChatResponse(reply=reply)


def _keyword_intent(text: str) -> IntentResult:
    bp_values = _parse_bp(text)

    if bp_values and not any(word in text for word in ["趋势", "最近", "一周", "七天", "统计"]):
        return IntentResult(
            intent="record_blood_pressure",
            params={"systolic": bp_values[0], "diastolic": bp_values[1]},
            confidence=0.9,
        )

    if any(word in text for word in ["血压", "收缩压", "舒张压", "高压", "低压"]):
        if any(word in text for word in ["趋势", "最近", "一周", "七天", "统计"]):
            return IntentResult(intent="view_trend", confidence=0.9)
        if bp_values:
            return IntentResult(
                intent="record_blood_pressure",
                params={"systolic": bp_values[0], "diastolic": bp_values[1]},
                confidence=0.9,
            )
        return IntentResult(intent="record_blood_pressure", confidence=0.5)

    if any(word in text for word in ["隐私", "同意", "政策", "免责"]):
        return IntentResult(intent="give_consent", confidence=0.9)

    if any(word in text for word in ["建档", "信息", "个人资料", "基本信息", "资料"]):
        return IntentResult(intent="create_profile", confidence=0.9)

    if any(word in text for word in ["你好", "嗨", "hello", "hi", "您好", "你是谁"]):
        return IntentResult(intent="greeting", confidence=0.9)

    if any(word in text for word in ["帮助", "功能", "能做什么", "可以做什么"]):
        return IntentResult(intent="ask_help", confidence=0.9)

    return IntentResult(intent="general_question", confidence=0.3)


async def _dispatch_intent(
    intent: IntentResult,
    text: str,
    session: AsyncSession,
    user_id: UUID,
) -> str:
    match intent.intent:
        case "record_blood_pressure":
            systolic = intent.params.get("systolic")
            diastolic = intent.params.get("diastolic")
            if systolic and diastolic:
                return await _handle_blood_pressure_values(
                    session, user_id, int(systolic), int(diastolic)
                )
            return await _handle_blood_pressure(text, session, user_id)

        case "view_trend":
            return await _handle_trend(session, user_id)

        case "give_consent":
            return await _handle_consent(text, session, user_id)

        case "create_profile":
            return await _handle_onboarding(session, user_id)

        case "greeting":
            return "您好！我是健健，您的个人慢病管理助手。我可以帮您记录血压、查看趋势、管理健康档案。请问有什么可以帮您的？"

        case "ask_help":
            return (
                "我可以帮您做以下事情：\n"
                "🩺 记录血压 - 直接告诉我血压值，如 '120/80'\n"
                "📊 查看趋势 - 输入'血压趋势'查看七日变化\n"
                "📋 健康建档 - 输入'建档'开始创建健康画像\n"
                "🔒 隐私政策 - 输入'隐私政策'了解更多\n"
                "有什么需要帮您的吗？"
            )

        case _:
            return get_disclaimer(DisclaimerType.KNOWLEDGE_QA)


async def _handle_blood_pressure_values(
    session: AsyncSession,
    user_id: UUID,
    systolic: int,
    diastolic: int,
) -> str:
    validation = validate_blood_pressure(systolic, diastolic)
    if not validation.is_valid:
        return validation.errors[0] if validation.errors else "血压数值不合法，请重新输入"

    confirmation = check_abnormal(systolic, diastolic)
    if confirmation.needs_confirmation:
        return confirmation.message

    await record_blood_pressure(
        session,
        user_id,
        BloodPressureData(systolic=systolic, diastolic=diastolic),
    )

    level = validation.systolic_level.value
    return f"已记录血压 {systolic}/{diastolic} mmHg（{level}）。继续保持监测！"