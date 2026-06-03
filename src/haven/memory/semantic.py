"""SemanticMemory — 自然语言知识存储。

存储 LLM 批量提取的自然语言事实陈述。每条事实是一个完整的中文句子，
由辅助模型从多轮对话中提取并合并去重后写入。

存储：SQLite 的 semantic_facts 表，与 EpisodicMemory 共享 .data/memory.db。
"""

from __future__ import annotations

from datetime import datetime
import json
import logging
from pathlib import Path
import sqlite3
from typing import Any

logger = logging.getLogger("haven.memory.semantic")

from haven.memory.base import BaseMemory, MemoryItem


class SemanticMemory(BaseMemory):
    """自然语言知识存储。每条事实为一个完整的中文句子。

    Schema:
      semantic_facts (entity_name, fact_text, importance, source_episode_ids)

    importance 是定性标签（high / medium / low），
    转换为 MemoryItem.importance 时映射为数值（0.9 / 0.6 / 0.3）。
    """

    name = "semantic"

    def __init__(self, db_path: str | Path | None = None):
        if db_path is None:
            db_path = Path.cwd() / ".data" / "memory.db"
        db_path = Path(db_path)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        # 先删除旧的 key-value 表（无向后兼容），再创建新的自然语言事实表
        self._conn.executescript("""
            DROP TABLE IF EXISTS memory_fact_history;
            DROP TABLE IF EXISTS memory_facts;
            DROP TABLE IF EXISTS memory_entities;

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

    # ========== 存储 ==========

    async def store(self, items: list[MemoryItem]) -> None:
        """兼容旧接口：逐个写入，importance 默认 medium。

        MemoryManager 的批量提取使用 store_facts() 全量替换，
        此方法用于兼容外部调用方。
        """
        for item in items:
            entity_name = item.metadata.get("entity_name", "user")
            fact_text = item.content
            if not fact_text:
                continue
            self._conn.execute(
                "INSERT INTO semantic_facts (entity_name, fact_text, importance) "
                "VALUES (?, ?, ?)",
                (entity_name, fact_text, "medium"),
            )
        self._conn.commit()

    async def store_facts(
        self,
        entity_name: str,
        facts: list[dict],
        source_episode_ids: list[str],
    ) -> None:
        """增量合并事实：新事实插入，已有事实更新。

        每条 fact 是 {"text": "...", "importance": "high|medium|low"}。
        已存在相同 fact_text + entity_name → 更新 importance + 合并来源；
        不存在 → 插入新行。
        旧事实不会被删除（由 consolidate 的 90 天过期清理负责）。
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
                # 合并来源 episode ID 列表
                try:
                    old_sources = json.loads(existing["source_episode_ids"])
                except (json.JSONDecodeError, TypeError):
                    old_sources = []
                new_sources = json.loads(source_json)
                merged_ids = list(set(old_sources + new_sources))
                merged_json = json.dumps(merged_ids, ensure_ascii=False)

                self._conn.execute(
                    "UPDATE semantic_facts SET importance = ?, "
                    "source_episode_ids = ?, updated_at = CURRENT_TIMESTAMP "
                    "WHERE id = ?",
                    (importance, merged_json, existing["id"]),
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
        logger.debug(
            "store_facts: %d inserted, %d updated for '%s'",
            inserted, updated, entity_name,
        )

    async def get_all_facts_text(self, entity_name: str) -> str:
        """获取某实体的所有事实，格式化为 '- 事实文本' 的字符串。

        供 LLM 批量提取 prompt 中的「已有知识」部分使用。
        按 importance 排序（high 在前）。
        """
        rows = self._conn.execute(
            "SELECT fact_text FROM semantic_facts WHERE entity_name = ? "
            "ORDER BY importance = 'high' DESC, created_at DESC",
            (entity_name,),
        ).fetchall()
        if not rows:
            return ""
        return "\n".join(f"- {r['fact_text']}" for r in rows)

    # ========== 检索 ==========

    async def retrieve(
        self, query: str = "", top_k: int = 10, **filters: Any
    ) -> list[MemoryItem]:
        """按 entity_name 和/或关键词检索事实。

        filters:
            entity_name: 限定实体（必传，否则查所有实体）
            query:       关键词 LIKE 匹配 fact_text

        排序：importance = 'high' 优先，再按创建时间倒序。
        """
        entity_name = filters.get("entity_name")

        where = ["1=1"]
        params: list[Any] = []

        if entity_name:
            where.append("entity_name = ?")
            params.append(entity_name)
        if query:
            # 简单 LIKE 匹配，无需全文索引（事实集通常不大）
            where.append("fact_text LIKE ?")
            params.append(f"%{query}%")

        rows = self._conn.execute(
            f"SELECT * FROM semantic_facts WHERE {' AND '.join(where)} "
            f"ORDER BY importance = 'high' DESC, created_at DESC LIMIT ?",
            [*params, top_k],
        ).fetchall()

        return [self._row_to_item(r) for r in rows]

    async def retrieve_entity_facts(
        self, entity_name: str
    ) -> list[MemoryItem]:
        """获取某实体的全部事实（最多 50 条）。"""
        return await self.retrieve(entity_name=entity_name, top_k=50)

    # ========== 遗忘 ==========

    async def forget(self, item_id: str) -> None:
        self._conn.execute(
            "DELETE FROM semantic_facts WHERE id=?", (int(item_id),)
        )
        self._conn.commit()

    async def clear(self) -> None:
        self._conn.execute("DELETE FROM semantic_facts")
        self._conn.commit()

    # ========== Consolidation ==========

    async def consolidate(self, llm: Any = None) -> int:
        """清理超过 90 天未更新的旧事实。

        去重和合并已由 LLM 在每次批量提取时完成，
        这里只做简单的过期清理，不需要 LLM 参与。
        """
        self._conn.execute(
            "DELETE FROM semantic_facts "
            "WHERE updated_at < datetime('now', '-90 days')"
        )
        self._conn.commit()
        return self._conn.total_changes

    # ========== 内部 ==========

    # importance 标签到数值的映射，用于 MemoryItem.importance
    _IMPORTANCE_MAP = {"high": 0.9, "medium": 0.6, "low": 0.3}

    def _row_to_item(self, row: Any) -> MemoryItem:
        """将 SQLite 行转换为 MemoryItem。

        content 直接使用 fact_text（自然语言句子），无需二次格式化。
        """
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
