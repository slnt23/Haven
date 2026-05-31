"""Checkpointer — 工作流状态持久化。

- Checkpointer ABC
- SQLiteCheckpointer（持久化到 .data/memory.db）
- MemoryCheckpointer（测试用）
"""

from __future__ import annotations

import json
import sqlite3
from abc import ABC, abstractmethod
from dataclasses import asdict
from pathlib import Path
from typing import Any


class Checkpointer(ABC):
    """状态持久化抽象。"""

    @abstractmethod
    async def save(self, session_id: str, node_name: str, state: Any) -> None:
        ...

    @abstractmethod
    async def load(self, session_id: str) -> Any | None:
        ...

    @abstractmethod
    async def list_sessions(self) -> list[dict[str, Any]]:
        ...


class SQLiteCheckpointer(Checkpointer):
    """基于 SQLite 的 Checkpointer。

    在 .data/memory.db 中新增 workflow_checkpoints 表。
    """

    def __init__(self, db_path: str | Path | None = None):
        if db_path is None:
            from haven.config import settings
            db_path = settings.project_root / ".data" / "memory.db"
        db_path = Path(db_path)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS workflow_checkpoints (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                node_name TEXT NOT NULL,
                state_json TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(session_id, node_name)
            );
            CREATE INDEX IF NOT EXISTS idx_checkpoint_session
                ON workflow_checkpoints(session_id, created_at DESC);
        """)
        self._conn.commit()

    async def save(self, session_id: str, node_name: str, state: Any) -> None:
        state_dict = _serialize(state)
        state_json = json.dumps(state_dict, ensure_ascii=False, default=str, indent=2)

        self._conn.execute("""
            INSERT INTO workflow_checkpoints (session_id, node_name, state_json)
            VALUES (?, ?, ?)
            ON CONFLICT(session_id, node_name) DO UPDATE SET
                state_json = excluded.state_json,
                created_at = CURRENT_TIMESTAMP
        """, (session_id, node_name, state_json))
        self._conn.commit()

    async def load(self, session_id: str) -> Any | None:
        row = self._conn.execute("""
            SELECT node_name, state_json FROM workflow_checkpoints
            WHERE session_id = ?
            ORDER BY created_at DESC LIMIT 1
        """, (session_id,)).fetchone()

        if row is None:
            return None
        return json.loads(row["state_json"])

    async def list_sessions(self) -> list[dict[str, Any]]:
        rows = self._conn.execute("""
            SELECT session_id, node_name, created_at
            FROM workflow_checkpoints
            WHERE node_name != '__END__'
            ORDER BY created_at DESC
        """).fetchall()
        return [dict(r) for r in rows]


class MemoryCheckpointer(Checkpointer):
    """内存 Checkpointer（测试用）。"""

    def __init__(self):
        self._store: dict[str, Any] = {}

    async def save(self, session_id: str, node_name: str, state: Any) -> None:
        self._store[session_id] = state

    async def load(self, session_id: str) -> Any | None:
        return self._store.get(session_id)

    async def list_sessions(self) -> list[dict[str, Any]]:
        return [
            {"session_id": k, "node_name": getattr(v, "current_node", ""), "created_at": ""}
            for k, v in self._store.items()
        ]


def _serialize(state: Any) -> dict:
    """序列化 state 为 dict，排除不可序列化的字段。"""
    if hasattr(state, "__dataclass_fields__"):
        d = asdict(state)
        for key in list(d):
            if key.startswith("_"):
                d[key] = None
        return d
    d = vars(state).copy()
    for key in list(d):
        if key.startswith("_"):
            d[key] = None
    return d
