"""MemoryManager —— 统一记忆管理入口。

整合短期记忆（LangGraph checkpointer）和长期记忆（FactMemory + VectorMemory）。
提供统一的 remember / recall / forget 接口。
ContextBuilder 通过 MemoryManager 获取上下文，不直接访问存储层。
"""

from __future__ import annotations

import logging
from typing import Any

from haven.memory.fact_store import FactStore
from haven.memory.extractor import FactExtractor

logger = logging.getLogger("haven.memory.manager")


class MemoryManager:
    """统一记忆管理器。

    短期记忆由 LangGraph SqliteSaver 自动处理（消息持久化）。
    长期记忆由 FactStore（SQLite 语义事实）负责。

    Usage::

        mgr = MemoryManager(fact_store, extractor=extractor)
        await mgr.remember("用户喜欢 Python", entity="user", importance=0.8)
        results = mgr.recall(query="Python", entity="user")
        mgr.forget(entity="user")
        await mgr.after_turn(user_input, agent_response, entity="user")
    """

    def __init__(
        self,
        fact_store: FactStore,
        *,
        extractor: FactExtractor | None = None,
        entity_name: str = "user",
    ) -> None:
        self._store = fact_store
        self._extractor = extractor
        self._entity = entity_name

    # ------------------------------------------------------------------
    # 公开接口：remember / recall / forget
    # ------------------------------------------------------------------

    def remember(
        self,
        content: str,
        *,
        entity: str | None = None,
        importance: float = 0.5,
        source: str = "conversation",
    ) -> int:
        """存储一条记忆事实。返回事实 ID。"""
        entity = entity or self._entity
        return self._store.add(
            entity_name=entity,
            content=content,
            importance=importance,
            source=source,
        )

    def recall(
        self,
        query: str = "",
        *,
        entity: str | None = None,
        limit: int = 10,
    ) -> list[Any]:
        """按关键词检索记忆。"""
        entity = entity or self._entity
        return self._store.search(query=query, entity_name=entity, limit=limit)

    def recall_text(self, entity: str | None = None) -> str:
        """获取实体的全部记忆，格式化为文本（供 ContextBuilder 使用）。"""
        entity = entity or self._entity
        return self._store.get_all_text(entity)

    def forget(self, entity: str | None = None) -> None:
        """清空指定实体的全部记忆。"""
        entity = entity or self._entity
        self._store.clear(entity)

    # ------------------------------------------------------------------
    # 公开接口：after_turn（从对话中提取并存储事实）
    # ------------------------------------------------------------------

    async def after_turn(
        self,
        user_input: str,
        agent_response: str,
        entity: str | None = None,
    ) -> int:
        """从一轮对话中提取事实并存储。返回写入数量。

        不阻塞调用方 —— 调用方应将其放入后台任务执行。
        """
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
        for f in facts:
            try:
                self._store.add(
                    entity,
                    f["content"],
                    importance=f.get("importance", 0.5),
                )
                written += 1
            except Exception:
                logger.warning("事实写入失败: %s", f.get("content", "")[:80])
        return written

    # ------------------------------------------------------------------
    # 存储访问
    # ------------------------------------------------------------------

    @property
    def store(self) -> FactStore:
        """直接访问底层存储（仅内部使用）。"""
        return self._store
