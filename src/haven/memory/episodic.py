"""EpisodicMemory — 完整对话记录存储。

SQLite 后端。每轮对话完整保留，支持关键词检索 + 时间衰减 + 重要性加权。
processed 字段用于语义批量提取的状态追踪。
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

    存储策略：每轮对话一行，保留原始消息 + 可选的 LLM 摘要。
    检索策略：关键词匹配 + 时间衰减 × 重要性加权（hybrid 模式）。

    processed 字段标记该轮对话是否已被语义提取处理过，
    由 MemoryManager 的批量提取流程写入。
    """

    name = "episodic"

    def __init__(self, db_path: str | Path | None = None):
        if db_path is None:
            db_path = Path.cwd() / ".data" / "memory.db"
        db_path = Path(db_path)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        # episodes 表：每轮对话一行
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
        # 幂等添加 processed 列（SQLite 不支持 ADD COLUMN IF NOT EXISTS）
        try:
            self._conn.execute(
                "ALTER TABLE episodes ADD COLUMN processed INTEGER NOT NULL DEFAULT 0"
            )
        except sqlite3.OperationalError:
            pass  # 列已存在
        self._conn.commit()

    # ========== 存储 ==========

    async def store(self, items: list[MemoryItem]) -> None:
        """通用存储接口。由 store_turn() 调用。"""
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
        """存储一轮完整对话。MemoryManager 的主写入入口。"""
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

    async def retrieve(
        self, query: str = "", top_k: int = 5, **filters: Any
    ) -> list[MemoryItem]:
        """按条件检索对话记录。

        filters:
            session_id:      限定会话
            time_range:      时间范围（如 "30d"、"7d"）
            min_importance:  最低重要性阈值
            search_mode:     "recent"（最近）/ "keyword"（关键词）/ "hybrid"（混合加权，默认）

        hybrid 模式使用公式: importance × 0.6 + 时间衰减 × 0.4
        """
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

        # 根据搜索模式选择排序方式
        if search_mode == "recent":
            order = "created_at DESC"
            extra: list[Any] = []
        elif search_mode == "keyword" and query:
            # 关键词模式：在所有文本字段中 LIKE 匹配
            where_sql += (
                " AND (user_message LIKE ? "
                "OR assistant_response LIKE ? OR summary LIKE ?)"
            )
            kw = f"%{query}%"
            extra = [kw, kw, kw]
            order = "importance DESC, created_at DESC"
        else:
            # hybrid: 重要性 60% + 时间衰减 40%
            # 时间衰减 = 1/(天数差+1)，越新权重越高
            extra = []
            order = (
                "importance * 0.6 + "
                "(1.0/(julianday('now')-julianday(created_at)+1.0))*0.4 DESC"
            )

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
        self._conn.execute("UPDATE episodes SET processed = 0")
        self._conn.commit()

    # ========== 批量提取 ==========

    async def count_unprocessed(self, session_id: str) -> int:
        """统计未处理的对话轮数。用于判断是否触发批量提取。"""
        row = self._conn.execute(
            "SELECT COUNT(*) as cnt FROM episodes "
            "WHERE processed = 0 AND session_id = ?",
            (session_id,),
        ).fetchone()
        return row["cnt"] if row else 0

    async def get_unprocessed(
        self, session_id: str, limit: int = 20
    ) -> list[dict]:
        """获取未处理的对话，按轮次升序排列。

        Returns:
            字典列表，每项含 id、turn_number、user_message、assistant_response
        """
        rows = self._conn.execute(
            "SELECT id, turn_number, user_message, assistant_response "
            "FROM episodes WHERE processed = 0 AND session_id = ? "
            "ORDER BY turn_number ASC LIMIT ?",
            (session_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    async def mark_processed(self, episode_ids: list[str]) -> None:
        """批量标记对话为已处理。

        使用参数化 SQL 的 IN 子句，避免 SQL 注入风险。
        """
        if not episode_ids:
            return
        placeholders = ",".join("?" * len(episode_ids))
        self._conn.execute(
            f"UPDATE episodes SET processed = 1 WHERE id IN ({placeholders})",
            episode_ids,
        )
        self._conn.commit()

    # ========== Consolidation ==========

    async def consolidate(self, llm: Any = None) -> int:
        """为超过 1 天的旧对话生成一句话摘要。

        仅处理 summary 为空且创建时间 > 1 天的记录，每次最多 20 条。
        使用辅助模型生成摘要后写回 summary 字段。
        """
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

                # 消息截断到 200 字符，控制 prompt 长度
                resp = await llm.ainvoke(
                    [
                        HumanMessage(
                            content=(
                                f"用一句话总结这段对话:\n"
                                f"用户:{row['user_message'][:200]}\n"
                                f"AI:{row['assistant_response'][:200]}\n"
                                f"总结:"
                            )
                        )
                    ]
                )
                summary = (
                    resp.content if hasattr(resp, "content") else str(resp)
                ).strip()
                self._conn.execute(
                    "UPDATE episodes SET summary=? WHERE id=?",
                    (summary, row["id"]),
                )
                count += 1
            except Exception:
                pass

        self._conn.commit()
        return count

    # ========== 内部 ==========

    def _row_to_item(self, row: Any) -> MemoryItem:
        """将 SQLite 行转换为 MemoryItem。

        检索时优先返回已生成的摘要，没有摘要则截取回复前 200 字符。
        """
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
    """解析时间范围字符串，如 "30d"、"7d"、"24h"。

    默认 7 天。
    """
    s = s.strip().lower()
    if s.endswith("d"):
        return timedelta(days=int(s[:-1]))
    elif s.endswith("h"):
        return timedelta(hours=int(s[:-1]))
    return timedelta(days=7)
