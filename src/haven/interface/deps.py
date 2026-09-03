from uuid import UUID

from fastapi import Header
from sqlalchemy.ext.asyncio import AsyncSession

from haven.infrastructure.database import get_session


async def get_db() -> AsyncSession:
    async for session in get_session():
        yield session


async def get_current_user_id(
    x_user_id: str = Header(default="", alias="X-User-ID"),
) -> UUID:
    if not x_user_id:
        raise ValueError("X-User-ID header is required")
    return UUID(x_user_id)