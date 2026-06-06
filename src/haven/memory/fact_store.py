"""FactStore — 自然语言知识存储。

SQLite 持久化的语义事实存储。基于 LLM 批量提取的自然语言事实陈述，
支持 upsert 合并去重和关键词检索。
"""

from __future__ import annotations

from datetime import datetime
import json
import logging
from pathlib import Path
import sqlite3
from typing import Any

from haven.memory.base import MemoryItem

logger = logging.getLogger("haven.memory.facts")


class FactStore:
    """SQLite 知识存储。每条事实是一个完整的中文句子。

    Schema: semantic_facts (entity_name, fact_text, importance, source_episode_ids)
    """

    _IMPORTANCE_MAP = {"high": 0.9, "medium": 0.6, "low": 0.3}

    def __init__(self, db_path: str | Path | None = None):
        if db_path is None:
            db_path = Path.cwd() / ".data" / "memory.db"
        db_path = Path(db_path)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS semantic_facts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                entity_name TEXT NOT NULL,
                fact_text TEXT NOT NULL,
                source_episode_ids TEXT NOT NULL DEFAULT '[]',
                importance TEXT NOT NULL DEFAULT 'medium',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_sf_entity ON semantic_facts(entity_name);
            CREATE INDEX IF NOT EXISTS idx_sf_importance ON semantic_facts(importance);
        """)
        self._conn.commit()

    def add_facts(
        self,
        entity_name: str,
        facts: list[dict],
        source_episode_ids: list[str],
    ) -> tuple[int, int]:
        """批量写入事实，已有事实合并来源并更新 importance。

        每条 fact: {"text": "...", "importance": "high|medium|low"}
        返回 (inserted, updated)。
        """
        source_json = json.dumps(source_episode_ids, ensure_ascii=False)
        inserted, updated = 0, 0

        for f in facts:
            text = f["text"]
            importance = f.get("importance", "medium")

            existing = self._conn.execute(
                "SELECT id, source_episode_ids FROM semantic_facts "
                "WHERE entity_name = ? AND fact_text = ?",
                (entity_name, text),
            ).fetchone()

            if existing:
                try:
                    old_sources = json.loads(existing["source_episode_ids"])
                except (json.JSONDecodeError, TypeError):
                    old_sources = []
                new_sources = json.loads(source_json)
                merged_ids = list(set(old_sources + new_sources))

                self._conn.execute(
                    "UPDATE semantic_facts SET importance = ?, "
                    "source_episode_ids = ?, updated_at = CURRENT_TIMESTAMP "
                    "WHERE id = ?",
                    (importance, json.dumps(merged_ids, ensure_ascii=False), existing["id"]),
                )
                updated += 1
            else:
                self._conn.execute(
                    "INSERT INTO semantic_facts "
                    "(entity_name, fact_text, source_episode_ids, importance) "
                    "VALUES (?, ?, ?, ?)",
                    (entity_name, text, source_json, importance),
                )
                inserted += 1

        self._conn.commit()
        logger.debug("add_facts: %d inserted, %d updated for '%s'", inserted, updated, entity_name)
        return inserted, updated

    def search(
        self, query: str = "", entity_name: str = "", top_k: int = 10,
    ) -> list[MemoryItem]:
        """按关键词和实体检索事实。"""
        where = ["1=1"]
        params: list[Any] = []

        if entity_name:
            where.append("entity_name = ?")
            params.append(entity_name)
        if query:
            where.append("fact_text LIKE ?")
            params.append(f"%{query}%")

        rows = self._conn.execute(
            f"SELECT * FROM semantic_facts WHERE {' AND '.join(where)} "
            "ORDER BY importance = 'high' DESC, created_at DESC LIMIT ?",
            [*params, top_k],
        ).fetchall()
        return [self._row_to_item(r) for r in rows]

    def get_all(self, entity_name: str) -> list[MemoryItem]:
        """获取某实体的所有事实。"""
        rows = self._conn.execute(
            "SELECT * FROM semantic_facts WHERE entity_name = ? "
            "ORDER BY importance = 'high' DESC, created_at DESC",
            (entity_name,),
        ).fetchall()
        return [self._row_to_item(r) for r in rows]

    def get_all_text(self, entity_name: str) -> str:
        """获取某实体的所有事实，格式化为 '- 事实' 文本。"""
        rows = self._conn.execute(
            "SELECT fact_text FROM semantic_facts WHERE entity_name = ? "
            "ORDER BY importance = 'high' DESC, created_at DESC",
            (entity_name,),
        ).fetchall()
        return "\n".join(f"- {r['fact_text']}" for r in rows) if rows else ""

    def delete(self, fact_id: int) -> None:
        self._conn.execute("DELETE FROM semantic_facts WHERE id = ?", (fact_id,))
        self._conn.commit()

    def clear(self) -> None:
        self._conn.execute("DELETE FROM semantic_facts")
        self._conn.commit()

    def expire_old(self, days: int = 90) -> int:
        """清理超过 N 天未更新的旧事实。返回删除数。"""
        self._conn.execute(
            "DELETE FROM semantic_facts WHERE updated_at < datetime('now', ?)",
            (f"-{days} days",),
        )
        self._conn.commit()
        return self._conn.total_changes

    def _row_to_item(self, row: Any) -> MemoryItem:
        return MemoryItem(
            id=str(row["id"]),
            content=row["fact_text"],
            memory_type="semantic",
            created_at=datetime.fromisoformat(row["created_at"]),
            importance=self._IMPORTANCE_MAP.get(row["importance"], 0.5),
            metadata={
                "entity_name": row["entity_name"],
                "importance": row["importance"],
                "source_episode_ids": row["source_episode_ids"],
            },
        )
