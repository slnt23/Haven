"""Checkpointer — 工作流状态持久化。

- Checkpointer ABC
- SQLiteCheckpointer（持久化到 .data/memory.db，V3 以 ExecutionState 为权威）
- MemoryCheckpointer（测试用）
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import asdict
import json
from pathlib import Path
import sqlite3
from typing import Any


class Checkpointer(ABC):
    """状态持久化抽象。"""

    @abstractmethod
    async def save(self, session_id: str, node_name: str, state: Any) -> None: ...

    @abstractmethod
    async def load(self, session_id: str) -> Any | None: ...

    @abstractmethod
    async def list_sessions(self) -> list[dict[str, Any]]: ...


class SQLiteCheckpointer(Checkpointer):
    """基于 SQLite 的 Checkpointer。

    在 .data/memory.db 中新增 workflow_checkpoints 表。
    V3: 以 ExecutionState 为权威执行快照，持久化 execution.snapshot()。
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
                execution_json TEXT,
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

        # V3: 单独持久化 ExecutionState 快照
        execution_json: str | None = None
        if hasattr(state, "execution") and state.execution is not None:
            try:
                es = state.execution
                execution_json = json.dumps(
                    es.snapshot(),
                    ensure_ascii=False,
                    default=str,
                    indent=2,
                )
            except Exception:
                pass

        self._conn.execute(
            """
            INSERT INTO workflow_checkpoints (session_id, node_name, state_json, execution_json)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(session_id, node_name) DO UPDATE SET
                state_json = excluded.state_json,
                execution_json = excluded.execution_json,
                created_at = CURRENT_TIMESTAMP
        """,
            (session_id, node_name, state_json, execution_json),
        )
        self._conn.commit()

    async def load(self, session_id: str) -> dict[str, Any] | None:
        """加载最近一个 checkpoint。

        Returns:
            dict with keys:
              - 'state': dict (raw state_json for backward compat)
              - 'execution': ExecutionState | None (reconstructed from snapshot)
              - 'node_name': str
        """
        row = self._conn.execute(
            """
            SELECT node_name, state_json, execution_json FROM workflow_checkpoints
            WHERE session_id = ?
            ORDER BY created_at DESC LIMIT 1
        """,
            (session_id,),
        ).fetchone()

        if row is None:
            return None

        result: dict[str, Any] = {
            "node_name": row["node_name"],
            "state": json.loads(row["state_json"]),
        }

        # V3: 从 execution_json 重建 ExecutionState
        if row["execution_json"]:
            try:
                from haven.runtime.execution import ExecutionState

                exec_data = json.loads(row["execution_json"])
                result["execution"] = ExecutionState.from_snapshot(exec_data)
            except Exception:
                result["execution"] = None
        else:
            result["execution"] = None

        return result

    async def list_sessions(self) -> list[dict[str, Any]]:
        rows = self._conn.execute("""
            SELECT session_id, node_name, created_at
            FROM workflow_checkpoints
            WHERE node_name != '__END__'
            ORDER BY created_at DESC
        """).fetchall()
        return [dict(r) for r in rows]


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
