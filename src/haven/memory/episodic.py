"""EpisodicMemory — 完整对话记录存储。

SQLite 后端。每轮对话完整保留，支持关键词检索 + 时间衰减 + 重要性加权。
"""

from __future__ import annotations

from datetime import datetime, timedelta
import json
from pathlib import Path
import sqlite3
from typing import Any
from uuid import uuid4

from haven.memory.base import BaseMemory, MemoryItem


class EpisodicMemory(BaseMemory):
    """对话记录存储。完整保留每轮对话。

    检索策略：关键词匹配 + 时间衰减 × 重要性加权。
    """

    name = "episodic"

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
            CREATE TABLE IF NOT EXISTS episodes (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                turn_number INTEGER NOT NULL,
                user_message TEXT NOT NULL,
                assistant_response TEXT NOT NULL,
                summary TEXT DEFAULT '',
                importance REAL DEFAULT 0.5,
                metadata_json TEXT DEFAULT '{}',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_episodes_session
                ON episodes(session_id, turn_number);
            CREATE INDEX IF NOT EXISTS idx_episodes_created
                ON episodes(created_at DESC);
        """)
        self._conn.commit()

    # ========== 存储 ==========

    async def store(self, items: list[MemoryItem]) -> None:
        for item in items:
            self._conn.execute(
                """
                INSERT OR REPLACE INTO episodes
                    (id, session_id, turn_number, user_message, assistant_response,
                     summary, importance, metadata_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    item.id,
                    item.metadata.get("session_id", "default"),
                    item.metadata.get("turn_number", 0),
                    item.metadata.get("user_message", ""),
                    item.content,
                    item.metadata.get("summary", ""),
                    item.importance,
                    json.dumps(item.metadata, ensure_ascii=False),
                ),
            )
        self._conn.commit()

    async def store_turn(
        self,
        session_id: str,
        turn_number: int,
        user_message: str,
        assistant_response: str,
        importance: float = 0.5,
    ) -> None:
        item = MemoryItem(
            id=f"ep_{session_id}_{turn_number}_{uuid4().hex[:8]}",
            content=assistant_response,
            memory_type="episodic",
            importance=importance,
            metadata={
                "session_id": session_id,
                "turn_number": turn_number,
                "user_message": user_message,
            },
        )
        await self.store([item])

    # ========== 检索 ==========

    async def retrieve(self, query: str = "", top_k: int = 5, **filters: Any) -> list[MemoryItem]:
        session_id = filters.get("session_id")
        time_range = filters.get("time_range")
        min_importance = filters.get("min_importance", 0.0)
        search_mode = filters.get("search_mode", "hybrid")

        where = ["1=1"]
        params: list[Any] = []

        if session_id:
            where.append("session_id = ?")
            params.append(session_id)
        if time_range:
            delta = _parse_time_range(time_range)
            cutoff = (datetime.now() - delta).isoformat()
            where.append("created_at >= ?")
            params.append(cutoff)
        if min_importance > 0:
            where.append("importance >= ?")
            params.append(min_importance)

        where_sql = " AND ".join(where)

        if search_mode == "recent":
            order = "created_at DESC"
            extra: list[Any] = []
        elif search_mode == "keyword" and query:
            where_sql += " AND (user_message LIKE ? OR assistant_response LIKE ? OR summary LIKE ?)"
            kw = f"%{query}%"
            extra = [kw, kw, kw]
            order = "importance DESC, created_at DESC"
        else:
            extra = []
            order = "importance * 0.6 + (1.0/(julianday('now')-julianday(created_at)+1.0))*0.4 DESC"

        rows = self._conn.execute(
            f"SELECT * FROM episodes WHERE {where_sql} ORDER BY {order} LIMIT ?",
            [*params, *extra, top_k],
        ).fetchall()

        return [self._row_to_item(r) for r in rows]

    # ========== 遗忘 ==========

    async def forget(self, item_id: str) -> None:
        self._conn.execute("DELETE FROM episodes WHERE id = ?", (item_id,))
        self._conn.commit()

    async def clear(self) -> None:
        self._conn.execute("DELETE FROM episodes")
        self._conn.commit()

    # ========== Consolidation ==========

    async def consolidate(self, llm: Any = None) -> int:
        rows = self._conn.execute("""
            SELECT id, user_message, assistant_response
            FROM episodes WHERE summary = ''
            AND created_at < datetime('now', '-1 day') LIMIT 20
        """).fetchall()
        if not rows or llm is None:
            return 0

        count = 0
        for row in rows:
            try:
                from langchain_core.messages import HumanMessage

                resp = await llm.ainvoke(
                    [
                        HumanMessage(
                            content=f"用一句话总结这段对话:\n用户:{row['user_message'][:200]}\nAI:{row['assistant_response'][:200]}\n总结:"
                        )
                    ]
                )
                summary = (resp.content if hasattr(resp, "content") else str(resp)).strip()
                self._conn.execute("UPDATE episodes SET summary=? WHERE id=?", (summary, row["id"]))
                count += 1
            except Exception:
                pass

        self._conn.commit()
        return count

    # ========== 内部 ==========

    def _row_to_item(self, row: Any) -> MemoryItem:
        meta = json.loads(row["metadata_json"]) if row["metadata_json"] else {}
        meta["session_id"] = row["session_id"]
        meta["turn_number"] = row["turn_number"]
        content = (
            f"用户: {row['user_message'][:200]}\n"
            f"AI: {row['summary'] or row['assistant_response'][:200]}"
        )
        return MemoryItem(
            id=row["id"],
            content=content,
            memory_type="episodic",
            created_at=datetime.fromisoformat(row["created_at"]),
            importance=row["importance"],
            metadata=meta,
        )


def _parse_time_range(s: str) -> timedelta:
    s = s.strip().lower()
    if s.endswith("d"):
        return timedelta(days=int(s[:-1]))
    elif s.endswith("h"):
        return timedelta(hours=int(s[:-1]))
    return timedelta(days=7)
