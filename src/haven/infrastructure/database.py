from typing import Any

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from haven.config.settings import Settings


class Base(DeclarativeBase):
    pass

_engine: Any = None
_session_factory: async_sessionmaker[AsyncSession] | None = None

def _get_engine(settings: Settings):
    engine = create_async_engine(
        settings.database_url,
        echo=False,
        connect_args={"check_same_thread": False},
    )
    return engine

async def init_db(settings: Settings)-> None:
    global _engine, _session_factory

    _engine = _get_engine(settings)

    async with _engine.begin() as conn:
        await conn.run_sync(
            lambda sync_conn: sync_conn.exec_driver_sql("PRAGMA journal_mode=WAL")
        )

        await conn.run_sync(
            lambda sync_conn: sync_conn.exec_driver_sql("PRAGMA foreign_keys=ON")
        )

    _session_factory = async_sessionmaker(
        _engine,   
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    
async def get_session() -> AsyncSession:
    if _session_factory is None:
        raise RuntimeError("Database session factory is not initialized. Call init_db first.")
    async with _session_factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

async def close_db() -> None:
    global _engine, _session_factory
    if _engine:
        await _engine.dispose()
        _engine = None
        _session_factory = None