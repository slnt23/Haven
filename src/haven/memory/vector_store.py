"""MemoryVectorStore —— 基于 LangChain 官方 VectorStore + Retriever 的记忆检索。

优先使用 LangChain Chroma + OpenAIEmbeddings。
若依赖缺失或 API Key 不可用，优雅降级（不阻断主流程）。
"""

from __future__ import annotations

import logging
from typing import Any

from haven.memory.base import MemoryItem

logger = logging.getLogger("haven.memory.vector_store")


class MemoryVectorStore:
    """LangChain 官方 VectorStore 封装。

    写入：FactStore 写入后，可选同步写入 VectorStore。
    检索：语义相似度检索，作为 SQLite LIKE 的增强。

    若 chromadb / langchain-chroma 未安装或 Embeddings API Key 不可用，
    则自动降级（_enabled=False），不影响主流程。
    """

    def __init__(
        self,
        persist_dir: str = "resource/chroma",
        collection_name: str = "haven_memory",
    ) -> None:
        self._store: Any = None
        self._retriever: Any = None
        self._enabled = False

        try:
            import chromadb  # noqa: F401
            from langchain_chroma import Chroma  # noqa: F401
        except ImportError:
            logger.debug(
                "langchain-chroma / chromadb 未安装，VectorStore 已禁用"
            )
            return

        try:
            from haven.config import load_config

            cfg = load_config()
            model = cfg.rag_embedding_model
            api_base = cfg.rag_embedding_api_base or None
            api_key = cfg.web_search_api_key or ""

            # 尝试使用 OpenAI 兼容的 Embeddings
            from langchain_openai import OpenAIEmbeddings

            embeddings = OpenAIEmbeddings(
                model=model,
                base_url=api_base,
                api_key=api_key or "sk-placeholder",
            )

            self._store = Chroma(
                collection_name=collection_name,
                embedding_function=embeddings,
                persist_directory=persist_dir,
                collection_metadata={"hnsw:space": "cosine"},
            )

            self._retriever = self._store.as_retriever(
                search_type="similarity",
                search_kwargs={"k": 5},
            )

            self._enabled = True
            logger.info("VectorStore 已启用 (Chroma: %s)", persist_dir)

        except Exception as exc:
            logger.warning("VectorStore 初始化失败，已禁用: %s", exc)

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------

    @property
    def enabled(self) -> bool:
        return self._enabled

    # ------------------------------------------------------------------
    # 清空
    # ------------------------------------------------------------------

    def clear(self, entity: str = "") -> None:
        """清空向量记忆。"""
        if not self._enabled:
            return
        try:
            if entity:
                self._store._collection.delete(where={"entity": entity})
            else:
                ids = self._store._collection.get()["ids"]
                if ids:
                    self._store._collection.delete(ids=ids)
        except Exception:
            logger.debug("VectorStore clear 失败", exc_info=True)

    # ------------------------------------------------------------------
    # 写入
    # ------------------------------------------------------------------

    def add(self, items: list[MemoryItem]) -> None:
        """批量添加记忆到 VectorStore。

        每条的 page_content = 事实文本，metadata 包含 entity / importance。
        """
        if not self._enabled or not items:
            return

        from langchain_core.documents import Document

        try:
            docs = [
                Document(
                    page_content=item.content,
                    metadata={
                        "entity": item.entity_name,
                        "importance": item.importance,
                        "source": item.source,
                    },
                )
                for item in items
            ]
            self._store.add_documents(docs)
        except Exception:
            logger.debug("VectorStore add 失败", exc_info=True)

    # ------------------------------------------------------------------
    # 检索
    # ------------------------------------------------------------------

    def search(
        self,
        query: str,
        *,
        entity: str = "",
        k: int = 5,
    ) -> list[dict]:
        """语义检索。若 VectorStore 不可用则返回空列表。

        Returns:
            list[dict]: [{"content": "...", "score": 0.9}, ...]
        """
        if not self._enabled:
            return []

        try:
            if entity and query:
                # 带过滤的语义检索
                results = self._store.similarity_search(
                    query, k=k, filter={"entity": entity},
                )
            elif query:
                results = self._retriever.invoke(query)
            else:
                # 无查询 → 返回最近添加的记忆
                results = self._store.similarity_search(
                    " ", k=k, filter={"entity": entity} if entity else None,
                )
        except Exception:
            logger.debug("VectorStore search 失败", exc_info=True)
            return []

        return [
            {
                "content": doc.page_content,
                "score": doc.metadata.get("score", 0.0),
                "entity": doc.metadata.get("entity", ""),
            }
            for doc in results
        ]
