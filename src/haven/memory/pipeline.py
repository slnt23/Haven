"""MemoryPipeline —— 长期语义记忆统一入口。

编排 extract → store 流程。Runtime 只调用此接口，
不直接接触 Extractor 或 FactStore。
"""

from __future__ import annotations

import logging
from typing import Any

from haven.memory.extractor import FactExtractor
from haven.memory.fact_store import FactStore

logger = logging.getLogger("haven.memory.pipeline")


class MemoryPipeline:
    """长期语义记忆管道。

    用法::

        pipeline = MemoryPipeline(extractor, store, entity_name="user")
        await pipeline.after_turn(user_input, agent_response)

    不阻塞调用方 —— 调用方应将其放入后台任务执行。
    """

    def __init__(
        self,
        extractor: FactExtractor,
        store: FactStore,
        *,
        entity_name: str = "user",
    ) -> None:
        self._extractor = extractor
        self._store = store
        self._entity = entity_name

    # ------------------------------------------------------------------
    # 公开 API
    # ------------------------------------------------------------------

    async def after_turn(self, user_input: str, agent_response: str) -> int:
        """从一轮对话中提取事实并写入存储。

        Returns:
            写入的事实数量。失败返回 0，不抛异常。
        """
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
                    self._entity,
                    f["content"],
                    importance=f.get("importance", 0.5),
                )
                written += 1
            except Exception:
                logger.warning("事实写入失败: %s", f.get("content", "")[:80])
        return written

    def clear(self) -> None:
        """清空当前实体的全部长期记忆。"""
        self._store.clear(self._entity)
