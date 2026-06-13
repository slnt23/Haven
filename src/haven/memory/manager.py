"""MemoryManager —— 统一记忆管理入口。

整合：
  - 短期记忆：LangGraph checkpointer（消息持久化）
  - 长期记忆：FactStore（SQLite 元数据）+ VectorStore（语义检索）

提供统一的 remember / retrieve / forget / after_turn 接口。
"""

from __future__ import annotations

import logging
from typing import Any

from haven.memory.base import MemoryItem
from haven.memory.fact_store import FactStore
from haven.memory.extractor import FactExtractor

logger = logging.getLogger("haven.memory.manager")


class MemoryManager:
    """统一记忆管理器。

    SQLite 负责元数据（id, importance, source, created_at）。
    VectorStore 负责 embedding + 语义检索（可选，降级时仅 SQLite）。

    Usage::

        mgr = MemoryManager(fact_store, extractor=extractor, vector_store=vs)
        items = mgr.retrieve(query="Python", entity="user")
    """

    def __init__(
        self,
        fact_store: FactStore,
        *,
        extractor: FactExtractor | None = None,
        vector_store: Any = None,
        entity_name: str = "user",
    ) -> None:
        self._store = fact_store
        self._extractor = extractor
        self._vector = vector_store
        self._entity = entity_name

    # ------------------------------------------------------------------
    # retrieve —— 统一检索入口（SQLite + VectorStore）
    # ------------------------------------------------------------------

    def retrieve(
        self,
        query: str = "",
        *,
        entity: str | None = None,
        limit: int = 10,
    ) -> list[MemoryItem]:
        """检索记忆（VectorStore 语义 + SQLite 元数据）。

        VectorStore 负责语义相似度排序。
        SQLite 负责补充元数据（importance, source, created_at）。
        VectorStore 不可用时回退到纯 SQLite LIKE。
        """
        entity = entity or self._entity

        # VectorStore 语义检索
        if self._vector is not None and self._vector.enabled and query:
            try:
                vs_results = self._vector.search(query, entity=entity, k=limit)
                if vs_results:
                    # 用 VectorStore 返回的内容去 SQLite 查元数据
                    items: list[MemoryItem] = []
                    for r in vs_results:
                        content = r.get("content", "")
                        if not content:
                            continue
                        # 尝试从 SQLite 获取完整元数据
                        sql_items = self._store.search(
                            query=content[:30], entity_name=entity, limit=1,
                        )
                        if sql_items:
                            items.append(sql_items[0])
                        else:
                            items.append(MemoryItem(
                                content=content,
                                entity_name=entity,
                                importance=r.get("score", 0.5),
                            ))
                    if items:
                        return items[:limit]
            except Exception:
                logger.debug("VectorStore 检索失败，回退 SQLite", exc_info=True)

        return self._store.search(query=query, entity_name=entity, limit=limit)

    def recall(
        self,
        query: str = "",
        *,
        entity: str | None = None,
        limit: int = 10,
    ) -> list[MemoryItem]:
        """等同于 retrieve。"""
        return self.retrieve(query=query, entity=entity, limit=limit)

    def recall_text(self, entity: str | None = None) -> str:
        """Deprecated: 推荐使用 retrieve() + ContextBuilder 格式化。"""
        items = self.retrieve(entity=entity, limit=100)
        if not items:
            return ""
        return "\n".join(f"- {i.content}" for i in items)

    # ------------------------------------------------------------------
    # remember / forget
    # ------------------------------------------------------------------

    def remember(
        self,
        content: str,
        *,
        entity: str | None = None,
        importance: float = 0.5,
        source: str = "conversation",
    ) -> int:
        entity = entity or self._entity
        return self._store.add(
            entity_name=entity, content=content,
            importance=importance, source=source,
        )

    def forget(self, entity: str | None = None) -> None:
        entity = entity or self._entity
        self._store.clear(entity)
        if self._vector is not None:
            try:
                self._vector.clear(entity=entity)
            except Exception:
                pass

    # ------------------------------------------------------------------
    # after_turn —— 提取 + 存储（SQLite + VectorStore）
    # ------------------------------------------------------------------

    async def after_turn(
        self,
        user_input: str,
        agent_response: str,
        entity: str | None = None,
    ) -> int:
        if self._extractor is None:
            return 0

        entity = entity or self._entity

        try:
            facts = await self._extractor.extract(user_input, agent_response)
        except Exception:
            logger.warning("事实提取失败", exc_info=True)
            return 0

        if not facts:
            return 0

        written = 0
        new_items: list[MemoryItem] = []
        for f in facts:
            try:
                fid = self._store.add(
                    entity, f["content"],
                    importance=f.get("importance", 0.5),
                )
                written += 1
                new_items.append(MemoryItem(
                    content=f["content"],
                    entity_name=entity,
                    importance=f.get("importance", 0.5),
                ))
            except Exception:
                logger.warning("事实写入失败: %s", f.get("content", "")[:80])

        # 同步写入 VectorStore
        if new_items and self._vector is not None:
            try:
                self._vector.add(new_items)
            except Exception:
                logger.debug("VectorStore 写入失败", exc_info=True)

        return written

    # ------------------------------------------------------------------
    # 存储访问
    # ------------------------------------------------------------------

    @property
    def store(self) -> FactStore:
        return self._store
