from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from haven.domain.models import (
    AllergyRecord,
    BloodPressure,
    ConsentRecord,
    DiseaseRecord,
    HealthProfile,
    User,
)


async def delete_user_data(
    session: AsyncSession,
    user_id: UUID,
) -> None:
    tables = [
        BloodPressure,
        DiseaseRecord,
        AllergyRecord,
        HealthProfile,
        ConsentRecord,
    ]

    for table in tables:
        stmt = select(table).where(table.user_id == user_id)
        result = await session.execute(stmt)
        records = result.scalars().all()
        for record in records:
            await session.delete(record)

    stmt = select(User).where(User.user_id == user_id)
    result = await session.execute(stmt)
    user = result.scalar_one_or_none()
    if user is not None:
        user.is_active = False
        user.deleted_at = datetime.now(UTC)

    await session.commit()