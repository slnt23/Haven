"""FactStore —— SQLite 语义事实存储。

存储自然语言事实句子，支持按实体查询和关键词检索。
LangChain / LangGraph 没有"语义事实存储"这个能力，
LangGraph Store 是通用 KV 存储，不处理自然语言事实的索引和去重。

每条事实是一个完整的中文句子，如"用户有高血压病史"。
"""

from __future__ import annotations

from datetime import datetime
import logging
from pathlib import Path
import sqlite3
from typing import Any

from haven.memory.base import MemoryItem

logger = logging.getLogger("haven.memory.facts")


class FactStore:
    """SQLite 语义事实存储。

    用途：存储从对话中提取的长期记忆事实，
    检索结果注入 system_prompt 作为上下文。

    Schema:
      facts(id, entity_name, content, importance, source, created_at)
    """

    def __init__(self, db_path: str | Path | None = None) -> None:
        if db_path is None:
            db_path = Path.cwd() / "resource" / "memory.db"
        db_path = Path(db_path)
        db_path.parent.mkdir(parents=True, exist_ok=True)

        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")  # 支持并发读
        self._init_schema()

    def _init_schema(self) -> None:
        """建表（幂等）。"""
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS facts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                entity_name TEXT NOT NULL,
                content TEXT NOT NULL,
                importance REAL NOT NULL DEFAULT 0.5,
                source TEXT NOT NULL DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_facts_entity ON facts(entity_name);
        """)
        self._conn.commit()

    # ------------------------------------------------------------------
    # 写入
    # ------------------------------------------------------------------

    def add(
        self,
        entity_name: str,
        content: str,
        *,
        importance: float = 0.5,
        source: str = "daily conversation",
    ) -> int:
        """添加一条事实。返回新行的 id。

        已存在的相同 (entity_name, content) 会更新 importance 而非重复插入。TODO：但是对于意思相同但是表达相近的还是有问题，例如：用户叫阿林，用户名叫阿林，
        """
        existing = self._conn.execute(
            "SELECT id FROM facts WHERE entity_name = ? AND content = ?",
            (entity_name, content),
        ).fetchone()

        if existing:
            self._conn.execute(
                "UPDATE facts SET importance = ?, source = ? WHERE id = ?",
                (importance, source, existing["id"]),
            )
            self._conn.commit()
            return existing["id"]

        cur = self._conn.execute(
            "INSERT INTO facts (entity_name, content, importance, source) "
            "VALUES (?, ?, ?, ?)",
            (entity_name, content, importance, source),
        )
        self._conn.commit()
        return cur.lastrowid

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------

    def search(
        self,
        query: str = "",
        *,
        entity_name: str = "",
        limit: int = 10,
    ) -> list[MemoryItem]:
        """关键词检索事实（LIKE 匹配）。"""
        where: list[str] = []
        params: list[Any] = []

        if entity_name:
            where.append("entity_name = ?")
            params.append(entity_name)
        if query:
            where.append("content LIKE ?")
            params.append(f"%{query}%")

        clause = " AND ".join(where) if where else "1=1"
        rows = self._conn.execute(
            f"SELECT * FROM facts WHERE {clause} "
            "ORDER BY importance DESC, created_at DESC LIMIT ?",
            (*params, limit),
        ).fetchall()
        return [_row_to_item(r) for r in rows]

    def get_all(self, entity_name: str) -> list[MemoryItem]:
        """获取某实体的全部事实（按重要性降序）。"""
        rows = self._conn.execute(
            "SELECT * FROM facts WHERE entity_name = ? "
            "ORDER BY importance DESC, created_at DESC",
            (entity_name,),
        ).fetchall()
        return [_row_to_item(r) for r in rows]

    def get_all_text(self, entity_name: str) -> str:
        """获取某实体的全部事实，格式化为 '- 事实内容' 文本。

        这是注入 system_prompt 的入口。
        """
        rows = self._conn.execute(
            "SELECT content FROM facts WHERE entity_name = ? "
            "ORDER BY importance DESC, created_at DESC",
            (entity_name,),
        ).fetchall()
        if not rows:
            return ""
        return "\n".join(f"- {r['content']}" for r in rows)

    # ------------------------------------------------------------------
    # 维护
    # ------------------------------------------------------------------

    def delete(self, fact_id: int) -> None:
        """按 ID 删除单条事实。"""
        self._conn.execute("DELETE FROM facts WHERE id = ?", (fact_id,))
        self._conn.commit()

    def clear(self, entity_name: str = "") -> None:
        """清空全部事实，或指定实体的全部事实。"""
        if entity_name:
            self._conn.execute(
                "DELETE FROM facts WHERE entity_name = ?", (entity_name,)
            )
        else:
            self._conn.execute("DELETE FROM facts")
        self._conn.commit()

    def expire(self, days: int = 90) -> int:
        """清理超过 N 天未更新的旧事实。返回删除数。"""
        self._conn.execute(
            "DELETE FROM facts WHERE created_at < datetime('now', ?)",
            (f"-{days} days",),
        )
        self._conn.commit()
        return self._conn.total_changes

    def close(self) -> None:
        """关闭数据库连接。"""
        self._conn.close()


# ------------------------------------------------------------------
# 内部
# ------------------------------------------------------------------


def _row_to_item(row: sqlite3.Row) -> MemoryItem:
    """SQLite Row → MemoryItem。"""
    return MemoryItem(
        content=row["content"],
        entity_name=row["entity_name"],
        importance=row["importance"],
        source=row["source"],
        created_at=datetime.fromisoformat(row["created_at"]),
    )
