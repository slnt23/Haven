"""MemoryManager —— 统一记忆管理入口。

整合：
  - 短期记忆：LangGraph checkpointer（消息持久化）
  - 长期记忆：FactStore（SQLite 元数据）+ VectorStore（语义检索 + 去重）

提供统一的 remember / retrieve / forget / after_turn 接口。
"""

from __future__ import annotations

import logging
from typing import Any

from haven.config import load_config
from haven.memory.base import MemoryItem
from haven.memory.fact_store import FactStore
from haven.memory.extractor import FactExtractor

logger = logging.getLogger("haven.memory.manager")


class MemoryManager:
    """统一记忆管理器。

    SQLite 负责元数据（id, importance, source, created_at）。
    VectorStore 负责 embedding + 语义检索 + 语义去重。
    """

    def __init__(
        self,
        fact_store: FactStore,
        *,
        extractor: FactExtractor | None = None,
        vector_store: Any = None,
        entity_name: str = "user",
        dedup_threshold: float | None = None,
    ) -> None:
        self._store = fact_store
        self._extractor = extractor
        self._vector = vector_store
        self._entity = entity_name
        self._dedup_threshold = (
            dedup_threshold
            if dedup_threshold is not None
            else load_config().memory.dedup_threshold
        )

    # ------------------------------------------------------------------
    # retrieve —— 统一检索入口
    # ------------------------------------------------------------------

    def retrieve(
        self,
        query: str = "",
        *,
        entity: str | None = None,
        limit: int = 10,
    ) -> list[MemoryItem]:
        """检索记忆（VectorStore 语义 + SQLite 元数据）。"""
        entity = entity or self._entity

        if self._vector is not None and self._vector.enabled and query:
            try:
                vs_results = self._vector.search(query, entity=entity, k=limit)
                if vs_results:
                    items: list[MemoryItem] = []
                    for r in vs_results:
                        content = r.get("content", "")
                        if not content:
                            continue
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
        self, query: str = "", *, entity: str | None = None, limit: int = 10,
    ) -> list[MemoryItem]:
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
        return self._dedup_and_store(entity, content, importance, source)

    def forget(self, entity: str | None = None) -> None:
        entity = entity or self._entity
        self._store.clear(entity)
        if self._vector is not None:
            try:
                self._vector.clear(entity=entity)
            except Exception:
                pass

    # ------------------------------------------------------------------
    # after_turn —— 提取 + 语义去重存储
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
                content = f["content"]
                imp = f.get("importance", 0.5)
                fid = self._dedup_and_store(entity, content, imp)
                if fid > 0:
                    written += 1
                new_items.append(MemoryItem(
                    content=content, entity_name=entity, importance=imp,
                ))
            except Exception:
                logger.warning("事实写入失败: %s", f.get("content", "")[:80])

        # 新增的事实写入 VectorStore（去重点击中的已通过 FactStore.add UPDATE 存在）
        truly_new = self._filter_new_items(new_items, entity)
        if truly_new and self._vector is not None:
            try:
                self._vector.add(truly_new)
            except Exception:
                logger.debug("VectorStore 写入失败", exc_info=True)

        return written

    # ------------------------------------------------------------------
    # 语义去重
    # ------------------------------------------------------------------

    def _dedup_and_store(
        self,
        entity: str,
        content: str,
        importance: float,
        source: str = "conversation",
    ) -> int:
        """语义去重 + 存储。

        1. VectorStore 检索 Top-3 相似记忆
        2. 如果 similarity >= threshold → UPDATE 已存在事实（提升 importance）
        3. 否则 → INSERT 新事实
        """
        # 语义相似检测
        if self._vector is not None and self._vector.enabled:
            try:
                similar = self._vector.search_similar(content, entity=entity, k=3)
                for s in similar:
                    if s["score"] >= self._dedup_threshold:
                        # 用相似内容的精确文本去触发 FactStore 的 UPDATE
                        existing_content = s["content"]
                        logger.debug(
                            "语义去重: '%.30s' ≈ '%.30s' (score=%.2f) → UPDATE",
                            content, existing_content, s["score"],
                        )
                        return self._store.add(
                            entity, existing_content,
                            importance=importance, source=source,
                        )
            except Exception:
                logger.debug("语义去重检测失败，按新增处理", exc_info=True)

        # 无相似 → 新增
        return self._store.add(
            entity, content, importance=importance, source=source,
        )

    def _filter_new_items(
        self,
        items: list[MemoryItem],
        entity: str,
    ) -> list[MemoryItem]:
        """过滤出真正新增的事实（不在 SQLite 中重复）。"""
        if not self._vector or not self._vector.enabled:
            return items
        existing = {i.content for i in self._store.search(entity_name=entity, limit=200)}
        return [i for i in items if i.content not in existing]

    # ------------------------------------------------------------------
    # 存储访问
    # ------------------------------------------------------------------

    @property
    def store(self) -> FactStore:
        return self._store
