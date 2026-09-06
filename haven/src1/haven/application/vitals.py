from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from haven.domain.models import BloodPressure


@dataclass(frozen=True)
class BloodPressureData:
    systolic: int
    diastolic: int
    measured_at: datetime | None = None
    source: str = "Manual"
    notes: str | None = None


@dataclass(frozen=True)
class BloodPressureResult:
    record: BloodPressure
    is_abnormal: bool
    abnormal_reason: str | None = None


async def record_blood_pressure(
    session: AsyncSession,
    user_id: UUID,
    data: BloodPressureData,
) -> BloodPressure:
    record = BloodPressure(
        user_id=user_id,
        systolic=data.systolic,
        diastolic=data.diastolic,
        measured_at=data.measured_at or datetime.now(UTC),
        source=data.source,
        notes=data.notes,
    )
    session.add(record)
    await session.commit()
    return record


async def get_blood_pressure_records(
    session: AsyncSession,
    user_id: UUID,
    since: datetime | None = None,
    limit: int = 100,
) -> list[BloodPressure]:
    stmt = select(BloodPressure).where(
        BloodPressure.user_id == user_id,
    )

    if since is not None:
        stmt = stmt.where(BloodPressure.measured_at >= since)

    stmt = stmt.order_by(BloodPressure.measured_at.desc()).limit(limit)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def check_duplicate(
    session: AsyncSession,
    user_id: UUID,
    systolic: int,
    diastolic: int,
    measured_at: datetime,
    window_seconds: int = 60,
) -> bool:
    stmt = select(BloodPressure).where(
        BloodPressure.user_id == user_id,
        BloodPressure.systolic == systolic,
        BloodPressure.diastolic == diastolic,
        BloodPressure.measured_at >= measured_at,
    )
    result = await session.execute(stmt)
    existing = result.scalars().all()
    for record in existing:
        diff = abs((record.measured_at - measured_at).total_seconds())
        if diff <= window_seconds:
            return True
    return False