"""SemanticMemory — 结构化知识存储。

实体-事实图。支持：多实体、事实变更历史、置信度衰减、按实体/标签/键检索。
"""

from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import sqlite3
from typing import Any

from haven.memory.base import BaseMemory, MemoryItem


class SemanticMemory(BaseMemory):
    """结构化知识存储。实体-事实-历史三层。

    Schema:
      memory_entities    — 实体对象
      memory_facts       — 事实（entity_id, key, value, confidence, tags）
      memory_fact_history — 事实变更历史（同 key 被覆盖时的旧值存档）
    """

    name = "semantic"

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
            CREATE TABLE IF NOT EXISTS memory_entities (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                type TEXT NOT NULL DEFAULT 'user',
                description TEXT DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS memory_facts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                entity_id INTEGER NOT NULL REFERENCES memory_entities(id),
                key TEXT NOT NULL,
                value TEXT NOT NULL,
                confidence REAL NOT NULL DEFAULT 0.9,
                source_session TEXT DEFAULT '',
                source_turn INTEGER DEFAULT 0,
                tags TEXT DEFAULT '[]',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(entity_id, key)
            );

            CREATE TABLE IF NOT EXISTS memory_fact_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                fact_id INTEGER NOT NULL REFERENCES memory_facts(id),
                old_value TEXT NOT NULL,
                new_value TEXT NOT NULL,
                changed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE INDEX IF NOT EXISTS idx_mf_entity ON memory_facts(entity_id);
            CREATE INDEX IF NOT EXISTS idx_mf_confidence ON memory_facts(confidence);
        """)
        self._conn.commit()

    # ========== 存储 ==========

    async def store(self, items: list[MemoryItem]) -> None:
        for item in items:
            entity_name = item.metadata.get("entity_name", "user")
            key = item.metadata.get("key", "")
            value = item.metadata.get("value", "") or item.content
            entity_type = item.metadata.get("entity_type", "user")

            if not key or not value:
                continue

            entity_id = self._get_or_create_entity(entity_name, entity_type)
            old_value = self._get_fact_value(entity_id, key)

            if old_value is not None and old_value != value:
                self._record_history(entity_id, key, old_value, value)

            self._upsert_fact(
                entity_id,
                key,
                value,
                confidence=item.metadata.get("confidence", item.importance),
                source_session=item.metadata.get("source_session", ""),
                source_turn=item.metadata.get("source_turn", 0),
                tags=json.dumps(item.metadata.get("tags", [])),
            )

    # ========== 检索 ==========

    async def retrieve(self, query: str = "", top_k: int = 10, **filters: Any) -> list[MemoryItem]:
        entity_name = filters.get("entity_name")
        key = filters.get("key")
        min_confidence = filters.get("min_confidence", 0.3)
        tag = filters.get("tag")

        where = ["f.confidence >= ?"]
        params: list[Any] = [min_confidence]
        joins = ["JOIN memory_entities e ON f.entity_id = e.id"]

        if entity_name:
            where.append("e.name = ?")
            params.append(entity_name)
        if key:
            where.append("f.key = ?")
            params.append(key)
        if tag:
            where.append("f.tags LIKE ?")
            params.append(f'%"{tag}"%')
        if query:
            where.append("(f.key LIKE ? OR f.value LIKE ?)")
            kw = f"%{query}%"
            params.extend([kw, kw])

        rows = self._conn.execute(
            f"SELECT f.*, e.name as entity_name, e.type as entity_type "
            f"FROM memory_facts f {' '.join(joins)} "
            f"WHERE {' AND '.join(where)} "
            f"ORDER BY f.confidence DESC, f.created_at DESC LIMIT ?",
            [*params, top_k],
        ).fetchall()

        return [self._row_to_item(r) for r in rows]

    async def retrieve_entity_facts(self, entity_name: str) -> list[MemoryItem]:
        return await self.retrieve(entity_name=entity_name, top_k=50)

    # ========== 遗忘 ==========

    async def forget(self, item_id: str) -> None:
        self._conn.execute("DELETE FROM memory_facts WHERE id=?", (int(item_id),))
        self._conn.commit()

    async def clear(self) -> None:
        self._conn.execute("DELETE FROM memory_facts")
        self._conn.execute("DELETE FROM memory_entities")
        self._conn.execute("DELETE FROM memory_fact_history")
        self._conn.commit()

    # ========== Consolidation ==========

    async def consolidate(self, llm: Any = None) -> int:
        self._conn.execute("""
            UPDATE memory_facts SET confidence = MAX(0.1, confidence - 0.1)
            WHERE confidence < 0.9 AND created_at < datetime('now', '-30 days')
        """)
        self._conn.execute("DELETE FROM memory_facts WHERE confidence <= 0.1")
        self._conn.commit()
        return self._conn.total_changes

    # ========== 内部 ==========

    def _get_or_create_entity(self, name: str, entity_type: str) -> int:
        self._conn.execute(
            "INSERT OR IGNORE INTO memory_entities (name, type) VALUES (?, ?)",
            (name, entity_type),
        )
        self._conn.commit()
        return self._conn.execute(
            "SELECT id FROM memory_entities WHERE name=?", (name,)
        ).fetchone()["id"]

    def _get_fact_value(self, entity_id: int, key: str) -> str | None:
        row = self._conn.execute(
            "SELECT value FROM memory_facts WHERE entity_id=? AND key=?",
            (entity_id, key),
        ).fetchone()
        return row["value"] if row else None

    def _record_history(self, entity_id: int, key: str, old: str, new: str) -> None:
        fact_row = self._conn.execute(
            "SELECT id FROM memory_facts WHERE entity_id=? AND key=?", (entity_id, key)
        ).fetchone()
        if fact_row:
            self._conn.execute(
                "INSERT INTO memory_fact_history (fact_id, old_value, new_value) VALUES (?,?,?)",
                (fact_row["id"], old, new),
            )
            self._conn.commit()

    def _upsert_fact(self, entity_id: int, key: str, value: str, **kw: Any) -> None:
        self._conn.execute(
            """
            INSERT INTO memory_facts
                (entity_id, key, value, confidence, source_session, source_turn, tags)
            VALUES (?,?,?,?,?,?,?)
            ON CONFLICT(entity_id, key) DO UPDATE SET
                value=excluded.value, confidence=excluded.confidence,
                source_session=excluded.source_session, source_turn=excluded.source_turn,
                tags=excluded.tags, created_at=CURRENT_TIMESTAMP
        """,
            (
                entity_id,
                key,
                value,
                kw.get("confidence", 0.9),
                kw.get("source_session", ""),
                kw.get("source_turn", 0),
                kw.get("tags", "[]"),
            ),
        )
        self._conn.commit()
        self._conn.execute(
            "UPDATE memory_entities SET updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (entity_id,),
        )
        self._conn.commit()

    def _row_to_item(self, row: Any) -> MemoryItem:
        return MemoryItem(
            id=str(row["id"]),
            content=f"{row['key']}: {row['value']}",
            memory_type="semantic",
            created_at=datetime.fromisoformat(row["created_at"]),
            importance=row["confidence"],
            metadata={
                "entity_name": row["entity_name"],
                "entity_type": row["entity_type"],
                "key": row["key"],
                "value": row["value"],
                "confidence": row["confidence"],
                "source_session": row["source_session"],
                "source_turn": row["source_turn"],
            },
        )
