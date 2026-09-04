from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from haven.domain.models import ConsentRecord
from haven.safety.disclaimers import DisclaimerType, get_disclaimer


@dataclass(frozen=True)
class ConsentResult:
    user_id: UUID
    policy_version: str
    consented: bool
    disclaimer_text: str


async def get_policy() -> str:
    return get_disclaimer(DisclaimerType.FIRST_USE)


async def record_consent(
    session: AsyncSession,
    user_id: UUID,
    policy_version: str,
    scope: str = "health_data_collection",
    ip_address: str | None = None,
) -> ConsentRecord:
    record = ConsentRecord(
        user_id=user_id,
        policy_version=policy_version,
        scope=scope,
        ip_address=ip_address,
    )
    session.add(record)
    await session.commit()
    return record


async def has_consented(
    session: AsyncSession,
    user_id: UUID,
) -> bool:
    stmt = select(ConsentRecord).where(
        ConsentRecord.user_id == user_id,
    ).limit(1)
    result = await session.execute(stmt)
    return result.scalars().first() is not None