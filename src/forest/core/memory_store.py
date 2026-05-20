"""Long-term memory store backed by SQLite.

Stores entities, their structured facts, conversation logs, and uses LLM
to automatically extract important facts from conversations.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import time
from pathlib import Path
from typing import Any

from forest.config import settings

logger = logging.getLogger("forest.memory_store")

EXTRACT_PROMPT = """\
从以下对话中提取关于对话中的"人"（用户）的重要结构化信息。

规则：
- 只提取明确陈述的事实，不要推测
- 每条事实用 key/value/confidence 三元组表示
- key 用英文 snake_case（如 "name", "job", "health_condition", "preference"）
- value 用原始语言保留
- confidence 用 0.0~1.0 评估确定性（0.9=明确陈述, 0.5=暗示, 0.3=猜测）
- 如果没有新事实，返回空数组 []
- 不要提取通用/无信息量的内容（如"你好"、"谢谢"这类社交用语）
- 重要的个人信息优先：姓名、职业、健康、偏好、目标、技能、联系方式等

对话内容:
{conversation}

仅返回 JSON 数组，无需其他内容:
{{
  "facts": [
    {{"key": "...", "value": "...", "confidence": 0.9}},
    ...
  ]
}}\
"""


class SQLiteMemoryStore:
    """SQLite-backed persistent memory for entities, facts, and conversations.

    Database file: ``.data/memory.db`` (configurable via settings).
    """

    def __init__(self, db_path: str | Path | None = None) -> None:
        if db_path is None:
            db_path = settings.project_root / ".data" / "memory.db"
        db_path = Path(db_path)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db_path = db_path
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    # ------------------------------------------------------------------
    # schema
    # ------------------------------------------------------------------

    def _init_schema(self) -> None:
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS entities (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                type TEXT NOT NULL DEFAULT 'person',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS entity_facts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                entity_id INTEGER NOT NULL REFERENCES entities(id),
                key TEXT NOT NULL,
                value TEXT NOT NULL,
                confidence REAL NOT NULL DEFAULT 0.9,
                source TEXT DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(entity_id, key)
            );

            CREATE TABLE IF NOT EXISTS conversations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                channel TEXT NOT NULL DEFAULT 'cli',
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE INDEX IF NOT EXISTS idx_conversations_session
                ON conversations(session_id, created_at);
            CREATE INDEX IF NOT EXISTS idx_facts_entity
                ON entity_facts(entity_id);
            CREATE INDEX IF NOT EXISTS idx_entities_name
                ON entities(name);
        """)
        self._conn.commit()

    # ------------------------------------------------------------------
    # entities
    # ------------------------------------------------------------------

    def get_or_create_entity(self, name: str, entity_type: str = "person") -> int:
        cur = self._conn.execute(
            "INSERT OR IGNORE INTO entities (name, type) VALUES (?, ?)",
            (name, entity_type),
        )
        self._conn.commit()
        row = self._conn.execute(
            "SELECT id FROM entities WHERE name = ?", (name,)
        ).fetchone()
        return row["id"]

    def get_entity_by_name(self, name: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT * FROM entities WHERE name = ?", (name,)
        ).fetchone()
        return dict(row) if row else None

    # ------------------------------------------------------------------
    # facts
    # ------------------------------------------------------------------

    def upsert_fact(
        self, entity_id: int, key: str, value: str,
        confidence: float = 0.9, source: str = "",
    ) -> None:
        self._conn.execute("""
            INSERT INTO entity_facts (entity_id, key, value, confidence, source)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(entity_id, key) DO UPDATE SET
                value = excluded.value,
                confidence = excluded.confidence,
                source = excluded.source,
                created_at = CURRENT_TIMESTAMP
        """, (entity_id, key, value, confidence, source))
        self._conn.commit()
        # touch entity updated_at
        self._conn.execute(
            "UPDATE entities SET updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (entity_id,),
        )
        self._conn.commit()

    def upsert_facts_batch(self, entity_id: int, facts: list[dict[str, Any]],
                           source: str = "") -> int:
        """Insert or update a batch of extracted facts. Returns count of facts written."""
        count = 0
        for fact in facts:
            key = fact.get("key", "")
            value = fact.get("value", "")
            if not key or not value:
                continue
            confidence = float(fact.get("confidence", 0.9))
            self.upsert_fact(entity_id, key, value, confidence, source)
            count += 1
        return count

    def get_facts(self, entity_id: int, min_confidence: float = 0.5) -> list[dict[str, Any]]:
        rows = self._conn.execute("""
            SELECT key, value, confidence, source, created_at
            FROM entity_facts
            WHERE entity_id = ? AND confidence >= ?
            ORDER BY created_at DESC
        """, (entity_id, min_confidence)).fetchall()
        return [dict(r) for r in rows]

    def get_facts_by_name(self, name: str, min_confidence: float = 0.5) -> list[dict[str, Any]]:
        entity = self.get_entity_by_name(name)
        if not entity:
            return []
        return self.get_facts(entity["id"], min_confidence)

    def format_facts_for_prompt(self, entity_id: int, min_confidence: float = 0.5) -> str:
        """Format entity facts as a system prompt injection snippet."""
        facts = self.get_facts(entity_id, min_confidence)
        if not facts:
            return ""
        lines = ["\n[长期记忆 — 以下是你已知的关于当前用户的信息]"]
        for f in facts:
            lines.append(f"- {f['key']}: {f['value']}")
        return "\n".join(lines)

    def format_facts_by_name(self, name: str, min_confidence: float = 0.5) -> str:
        entity = self.get_entity_by_name(name)
        if not entity:
            return ""
        return self.format_facts_for_prompt(entity["id"], min_confidence)

    # ------------------------------------------------------------------
    # conversations
    # ------------------------------------------------------------------

    def save_message(self, session_id: str, role: str, content: str,
                     channel: str = "cli") -> int:
        cur = self._conn.execute(
            "INSERT INTO conversations (session_id, channel, role, content) VALUES (?, ?, ?, ?)",
            (session_id, channel, role, content),
        )
        self._conn.commit()
        return cur.lastrowid

    def get_recent_messages(self, session_id: str, limit: int = 20) -> list[dict[str, Any]]:
        rows = self._conn.execute("""
            SELECT role, content, created_at
            FROM conversations
            WHERE session_id = ?
            ORDER BY created_at DESC
            LIMIT ?
        """, (session_id, limit)).fetchall()
        return [dict(r) for r in reversed(rows)]

    def get_last_conversation_pair(self, session_id: str) -> tuple[str, str]:
        """Return (user_message, ai_response) of the most recent exchange."""
        rows = self._conn.execute("""
            SELECT role, content FROM conversations
            WHERE session_id = ?
            ORDER BY id DESC LIMIT 2
        """, (session_id,)).fetchall()
        user_msg = ""
        ai_msg = ""
        for r in reversed(rows):
            if r["role"] == "human":
                user_msg = r["content"]
            elif r["role"] == "ai":
                ai_msg = r["content"]
        return user_msg, ai_msg

    # ------------------------------------------------------------------
    # LLM-powered extraction
    # ------------------------------------------------------------------

    async def extract_and_store(
        self, entity_name: str, conversation_snippet: str,
        llm: Any, source: str = "",
    ) -> list[dict[str, Any]]:
        """Use LLM to extract facts from a conversation and store them.

        Returns the list of extracted facts.
        """
        if not conversation_snippet.strip():
            return []

        prompt = EXTRACT_PROMPT.format(conversation=conversation_snippet)

        try:
            from langchain_core.messages import HumanMessage
            response = await llm.ainvoke([HumanMessage(content=prompt)])
            content = response.content if hasattr(response, "content") else str(response)
        except Exception as exc:
            logger.warning("Memory extraction LLM call failed: %s", exc)
            return []

        facts = self._parse_extraction(content)
        if not facts:
            return []

        entity_id = self.get_or_create_entity(entity_name)
        count = self.upsert_facts_batch(entity_id, facts, source)
        logger.info("Memory: extracted %d fact(s) for '%s'", count, entity_name)
        return facts

    @staticmethod
    def _parse_extraction(raw: str) -> list[dict[str, Any]]:
        """Parse LLM extraction response into a list of fact dicts."""
        # trim to JSON
        raw = raw.strip()
        # remove markdown fences if present
        if raw.startswith("```"):
            lines = raw.split("\n")
            raw = "\n".join(lines[1:]) if len(lines) > 1 else raw
            if raw.endswith("```"):
                raw = raw[:-3]
        # find JSON object
        brace_start = raw.find("{")
        if brace_start == -1:
            return []
        try:
            data = json.loads(raw[brace_start:])
        except json.JSONDecodeError:
            logger.debug("Failed to parse extraction JSON: %s", raw[:200])
            return []
        return data.get("facts", [])

    # ------------------------------------------------------------------
    # lifecycle
    # ------------------------------------------------------------------

    def close(self) -> None:
        self._conn.close()

    def __del__(self) -> None:
        try:
            self._conn.close()
        except Exception:
            pass
