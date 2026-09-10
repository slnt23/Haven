"""异步数据库层 —— 懒初始化引擎 + 统一会话作用域。

- 配置：`DATABASE_URL` 等环境配置见 `config.py`（单一来源）
  （开发默认 sqlite，部署须为 PostgreSQL，同一 SQLAlchemy URL 互换）。
- 所有数据库异常统一包装为 `DatabaseUnavailable`，工具层只捕获这一种。
- 会话在作用域干净退出时自动 commit，异常时自动 rollback。
"""

from __future__ import annotations

import asyncio
import logging
import re
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from config import get_settings


_logger = logging.getLogger(__name__)


class DatabaseUnavailable(Exception):
    """数据库不可用（连接失败 / 初始化失败等）。工具捕获后返回固定降级文案。"""


class Base(DeclarativeBase):
    pass


_engine = None
_session_factory: async_sessionmaker[AsyncSession] | None = None
_init_lock = asyncio.Lock()
_init_done = False


def _sqlite_path(url: str) -> Path | None:
    """sqlite+aiosqlite:///./data/haven.db -> Path('./data/haven.db')；内存库返回 None。"""
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


def _runtime_actor(runtime) -> tuple[str | None, str | None]:
    """取运行时注入的调用者 ``(kind, id)``，取不到返回 ``(None, None)``。

    MDA 的 ``runtime.identity`` 形状是 ``{"user": {"kind": "person"|"service",
    "id": str}, ...}``（vendored runtime `_identity_runtime.py:74-115`）；
    它只在平台注入可信 ``langgraph_auth_user`` 时才存在，作者侧无法控制。
    """
    try:
        user = runtime.identity["user"]
        kind = user.get("kind") if hasattr(user, "get") else None
        actor = user["id"]
        return (str(kind) if kind else None, str(actor) if actor else None)
    except Exception:  # noqa: BLE001 —— 没有 identity 是常态，不是错误
        return None, None


def caller_user_id(runtime) -> str | None:
    """本部署唯一服务的用户 id —— **身份由配置授予，运行时身份只用于否决**。

    单租户：一个部署 = 一个人，本人 id 来自 `HAVEN_OWNER_ID`（见 ADR-006）。
    不从运行时身份推导，是因为它在各运行方式下都不一样、且都不是"人"：

    - 本机 `mda dev`：合成服务主体 ``mda:local-dev``（换台机器就换身份）；
    - LangGraph Studio：``langgraph-studio-user``；
    - 部署后持 LangSmith key：``langsmith:user:<key 属主 id>``，且被标成
      ``kind: "service"``—— 那里根本没有"人"的身份，谁持有 key 谁就到达部署。

    所以：**没有运行时身份、或它是平台服务主体（channel / schedule / 本地 dev）
    时，都用配置的 owner id**；只有真正的 ``kind == "person"`` 身份才参与校验，
    与配置不符则拒绝（返回 None）。这条校验在当前的 LangSmith-key 部署下不会
    触发，它是为将来接 Supabase（每人一个 person 身份）准备的纵深防御 ——
    真正拦住外人的仍然是 `identity.py` 的认证。
    """
    owner = get_settings().owner_id
    kind, actor = _runtime_actor(runtime)
    if kind != "person":
        # 没有身份（本机 dev 未走认证路径、作者环境）或平台服务主体
        # （mda:local-dev / channel / schedule）—— 都不是"另一个人"，用配置值。
        return owner
    if actor == owner:
        return owner
    _logger.warning(
        "拒绝非本人的调用者：期望 user id %r，实际 %r。"
        "若这是你自己，请把 HAVEN_OWNER_ID 设为该值。",
        owner,
        actor,
    )
    return None
