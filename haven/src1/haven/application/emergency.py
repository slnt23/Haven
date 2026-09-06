from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from haven.domain.models import AuditLog
from haven.safety.emergency import (
    EMERGENCY_RESPONSE_CN,
    EmergencyLevel,
    detect_emergency,
)
from haven.safety.state_machine import SafetyContext, SafetyState


@dataclass(frozen=True)
class EmergencyCheckResult:
    is_emergency: bool
    response: str
    level: EmergencyLevel
    reason: str


def check_emergency(text: str) -> EmergencyCheckResult:
    result = detect_emergency(text)

    if result.level == EmergencyLevel.CONFIRMED:
        return EmergencyCheckResult(
            is_emergency=True,
            response=EMERGENCY_RESPONSE_CN,
            level=result.level,
            reason=result.reason,
        )

    return EmergencyCheckResult(
        is_emergency=False,
        response="",
        level=result.level,
        reason=result.reason,
    )


async def log_emergency_event(
    session: AsyncSession,
    user_id: UUID | None,
    event_type: str,
    reason: str,
    rule_version: str = "0.0.1",
) -> AuditLog:
    event_summary = f"emergency:{event_type}:{reason}"
    log = AuditLog(
        user_id=user_id,
        event_type=event_type,
        event_summary=event_summary[:500],
        rule_version=rule_version,
    )
    session.add(log)
    await session.commit()
    return log


def apply_emergency_state(
    context: SafetyContext,
    result: EmergencyCheckResult,
) -> SafetyContext:
    if result.is_emergency:
        context.transition_to(SafetyState.EMERGENCY)
    return context