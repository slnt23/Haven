"""异步数据库层 —— 懒初始化引擎 + 统一会话作用域。

- 配置：pydantic-settings 读 `.env` 的 `DATABASE_URL`
  （开发默认 sqlite，部署须为 PostgreSQL，同一 SQLAlchemy URL 互换）。
- 所有数据库异常统一包装为 `DatabaseUnavailable`，工具层只捕获这一种。
- 会话在作用域干净退出时自动 commit，异常时自动 rollback。
"""

from __future__ import annotations

import asyncio
import re
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

DEFAULT_DATABASE_URL = "sqlite+aiosqlite:///./data/haven.db"


class DatabaseUnavailable(Exception):
    """数据库不可用（连接失败 / 初始化失败等）。工具捕获后返回固定降级文案。"""


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        # .env 中留空的占位（DATABASE_URL=）不覆盖默认值。
        env_ignore_empty=True,
    )

    database_url: str = DEFAULT_DATABASE_URL
    log_level: str = "INFO"


class Base(DeclarativeBase):
    pass


_settings: Settings | None = None
_engine = None
_session_factory: async_sessionmaker[AsyncSession] | None = None
_init_lock = asyncio.Lock()
_init_done = False


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def _sqlite_path(url: str) -> Path | None:
    """sqlite+aiosqlite:///./db/haven.db -> Path('./db/haven.db')；内存库返回 None。"""
    if not url.startswith("sqlite"):
        return None
    match = re.match(r"^sqlite(?:\+[a-z]+)?:///?(.*)$", url)
    if not match:
        return None
    path = match.group(1)
    if not path or path == ":memory:":
        return None
    return Path(path)


async def ensure_initialized() -> None:
    """进程内懒初始化：建目录、建引擎、建表（幂等）。"""
    global _engine, _session_factory, _init_done
    if _init_done and _session_factory is not None:
        return

    async with _init_lock:
        if _init_done:
            return
        try:
            settings = get_settings()
            url = settings.database_url

            sqlite_file = _sqlite_path(url)
            if sqlite_file is not None:
                sqlite_file.parent.mkdir(parents=True, exist_ok=True)

            engine = create_async_engine(url, echo=False)
            # 注册 ORM 表（导入即注册到 Base.metadata）。
            from storage import models  # noqa: F401

            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)

            _engine = engine
            _session_factory = async_sessionmaker(
                engine,
                expire_on_commit=False,
            )
            _init_done = True
        except Exception as exc:  # noqa: BLE001 —— 统一包装给工具层
            raise DatabaseUnavailable(str(exc)) from exc


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    """干净的会话作用域：成功退出自动 commit；任何异常 rollback 并包装。"""
    await ensure_initialized()
    session = _session_factory()
    try:
        yield session
        await session.commit()
    except DatabaseUnavailable:
        await session.rollback()
        raise
    except Exception as exc:  # noqa: BLE001
        await session.rollback()
        raise DatabaseUnavailable(str(exc)) from exc
    finally:
        await session.close()


def caller_user_id(runtime) -> str | None:
    """从注入的运行时取当前调用者稳定 id。

    部署期由 MDA 注入（LangSmith-key 主体或经认证的终端用户）；
    仅作者环境（无 runtime 注入）返回 None，由工具层兜底。
    """
    try:
        identity = runtime.identity
        user_id = identity["user"]["id"]
        return str(user_id) if user_id else None
    except Exception:  # noqa: BLE001
        return None
