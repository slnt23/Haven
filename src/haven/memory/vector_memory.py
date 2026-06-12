"""VectorMemory —— 基于 ChromaDB 的向量语义检索（可选组件）。

优先使用 LangChain 官方 VectorStore 能力。
若 ChromaDB 未安装则优雅降级为空操作。
"""

from __future__ import annotations

import logging
from typing import Any

from haven.memory.base import MemoryItem

logger = logging.getLogger("haven.memory.vector")


class VectorMemory:
    """向量语义记忆。

    基于 ChromaDB + LangChain embeddings。
    用于语义相似度检索，补充 FactStore 的关键词匹配。

    若 ChromaDB 未安装则降级为空操作。
    """

    def __init__(
        self,
        collection_name: str = "haven_memory",
        persist_dir: str = "resource/chroma",
    ) -> None:
        self._collection: Any = None
        self._enabled = False

        try:
            import chromadb
            from chromadb.config import Settings

            client = chromadb.PersistentClient(
                path=persist_dir,
                settings=Settings(anonymized_telemetry=False),
            )
            self._collection = client.get_or_create_collection(
                name=collection_name,
                metadata={"hnsw:space": "cosine"},
            )
            self._enabled = True
            logger.info("VectorMemory 已启用 (ChromaDB: %s)", persist_dir)
        except ImportError:
            logger.debug("ChromaDB 未安装，VectorMemory 已禁用")
        except Exception as exc:
            logger.warning("VectorMemory 初始化失败: %s", exc)

    @property
    def enabled(self) -> bool:
        return self._enabled

    def add(self, items: list[MemoryItem]) -> None:
        """批量添加记忆到向量库。"""
        if not self._enabled or not items:
            return
        try:
            ids = [str(i.created_at.timestamp()) + "_" + i.content[:20] for i in items]
            docs = [i.content for i in items]
            metadatas = [
                {"entity": i.entity_name, "importance": i.importance, "source": i.source}
                for i in items
            ]
            self._collection.add(ids=ids, documents=docs, metadatas=metadatas)
        except Exception:
            logger.debug("VectorMemory add 失败", exc_info=True)

    def search(self, query: str, *, entity: str = "", limit: int = 5) -> list[dict]:
        """语义检索。"""
        if not self._enabled:
            return []
        try:
            where = {"entity": entity} if entity else None
            results = self._collection.query(
                query_texts=[query],
                n_results=limit,
                where=where,
            )
            if not results or not results.get("documents") or not results["documents"][0]:
                return []
            return [
                {"content": doc, "metadata": meta}
                for doc, meta in zip(
                    results["documents"][0],
                    results["metadatas"][0] if results.get("metadatas") else [],
                )
            ]
        except Exception:
            logger.debug("VectorMemory search 失败", exc_info=True)
            return []

    def clear(self, entity: str = "") -> None:
        """清空向量记忆。"""
        if not self._enabled:
            return
        try:
            if entity:
                self._collection.delete(where={"entity": entity})
            else:
                # 删除所有
                ids = self._collection.get()["ids"]
                if ids:
                    self._collection.delete(ids=ids)
        except Exception:
            logger.debug("VectorMemory clear 失败", exc_info=True)
