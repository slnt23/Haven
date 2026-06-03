"""VectorMemory — 向量语义记忆。

ChromaDB 后端。基于 embedding 的语义相似性检索，跨 session 模式匹配。

降级策略：chromadb 未安装 → 静默降级为空操作。
embedding 模型使用 app.yaml 中 RAG 段配置的模型（默认 text-embedding-3-small）。
"""

from __future__ import annotations

from datetime import datetime
import logging
from pathlib import Path
from typing import Any

from haven.memory.base import BaseMemory, MemoryItem

logger = logging.getLogger("haven.memory.vector")


class VectorMemory(BaseMemory):
    """向量语义记忆。基于 embedding 的相似性检索。

    存储后端：ChromaDB（持久化到 .data/chroma/）
    检索方式：query → embedding → cosine 相似度 → top_k

    降级策略：chromadb 未安装 → 静默降级，store/retrieve 均为空操作。
    """

    name = "vector"

    def __init__(
        self,
        collection_name: str = "haven_memory",
        persist_dir: str | None = None,
    ):
        self._collection_name = collection_name
        # 延迟初始化：首次调用 store/retrieve 时才连接 ChromaDB
        self._client = None
        self._collection = None
        self._embedding_fn = None

        if persist_dir is None:
            from haven.config import settings

            persist_dir = str(Path.cwd() / ".data" / "chroma")

        self._persist_dir = persist_dir

    # ========== 延迟初始化 ==========

    def _ensure_client(self) -> bool:
        """确保 ChromaDB 客户端可用。

        返回 False 表示不可用（chromadb 未安装或初始化失败），
        后续操作静默降级。
        """
        if self._client is not None:
            return self._client is not False
        try:
            import chromadb

            self._client = chromadb.PersistentClient(path=self._persist_dir)
            self._collection = self._client.get_or_create_collection(
                name=self._collection_name,
                metadata={"hnsw:space": "cosine"},  # 余弦相似度
            )
            return True
        except ImportError:
            logger.warning(
                "chromadb not installed — VectorMemory disabled. "
                "Install with: pip install chromadb"
            )
            self._client = False
            return False
        except Exception as exc:
            logger.warning("ChromaDB init failed: %s", exc)
            self._client = False
            return False

    def _ensure_embedding(self) -> bool:
        """确保 embedding 模型可用。

        使用 OpenAI-compatible embedding API，
        model 名称和 base URL 从 app.yaml RAG 段读取。
        """
        if self._embedding_fn is not None:
            return self._embedding_fn is not False
        try:
            from langchain_openai import OpenAIEmbeddings

            from haven.config import settings

            self._embedding_fn = OpenAIEmbeddings(
                model=settings.rag_embedding_model,
                openai_api_base=settings.rag_embedding_api_base,
                openai_api_key="none",  # 由 OpenAIEmbeddings 内部处理
            )
            return True
        except Exception as exc:
            logger.warning("Embedding init failed: %s", exc)
            self._embedding_fn = False
            return False

    @property
    def _available(self) -> bool:
        """客户端和 embedding 同时可用才算 ready。"""
        return self._ensure_client() and self._ensure_embedding()

    # ========== 存储 ==========

    async def store(self, items: list[MemoryItem]) -> None:
        """嵌入并存储到 ChromaDB。

        每个 MemoryItem 被转换为：
        - id: item.id
        - document: item.content（要嵌入的文本）
        - metadata: 所有可序列化的 item.metadata 字段

        静默降级：不可用时跳过。
        """
        if not items or not self._available:
            return

        texts = [item.content for item in items]
        ids = [item.id for item in items]
        # 元数据需序列化为字符串（ChromaDB 不支持嵌套结构）
        metadatas = [
            {
                "memory_type": item.memory_type,
                "importance": item.importance,
                "created_at": item.created_at.isoformat(),
                **{f"m_{k}": str(v)[:1000] for k, v in item.metadata.items()},
            }
            for item in items
        ]

        try:
            embeddings = await self._embedding_fn.aembed_documents(texts)
            self._collection.add(
                ids=ids,
                embeddings=embeddings,
                documents=texts,
                metadatas=metadatas,
            )
        except Exception as exc:
            logger.warning("VectorMemory store failed: %s", exc)

    # ========== 检索 ==========

    async def retrieve(
        self, query: str = "", top_k: int = 5, **filters: Any
    ) -> list[MemoryItem]:
        """按语义相似度检索。

        流程：query → embedding → ChromaDB cosine 相似度查询 → top_k

        filters 支持: session_id, memory_type, min_importance
        静默降级：query 为空或不可用时返回空列表。
        """
        if not query or not self._available:
            return []

        where = _build_chroma_filter(filters)

        try:
            query_emb = await self._embedding_fn.aembed_query(query)
            results = self._collection.query(
                query_embeddings=[query_emb],
                n_results=top_k,
                where=where if where else None,
            )
        except Exception as exc:
            logger.warning("VectorMemory retrieve failed: %s", exc)
            return []

        items: list[MemoryItem] = []
        if results and results.get("ids") and results["ids"][0]:
            for i, doc_id in enumerate(results["ids"][0]):
                doc = results["documents"][0][i] if results.get("documents") else ""
                meta = (
                    results["metadatas"][0][i]
                    if results.get("metadatas")
                    else {}
                )
                distance = (
                    results["distances"][0][i]
                    if results.get("distances")
                    else 0.0
                )
                # cosine 距离转相似度分数
                score = 1.0 - distance

                created = datetime.now()
                if "created_at" in meta:
                    try:
                        created = datetime.fromisoformat(meta["created_at"])
                    except (ValueError, TypeError):
                        pass

                item = MemoryItem(
                    id=doc_id,
                    content=doc,
                    memory_type="vector",
                    importance=meta.get("importance", 0.5),
                    metadata=meta,
                    created_at=created,
                )
                item.metadata["_score"] = score
                items.append(item)

        return items

    # ========== 遗忘 ==========

    async def forget(self, item_id: str) -> None:
        if self._available and self._collection:
            try:
                self._collection.delete(ids=[item_id])
            except Exception:
                pass

    async def clear(self) -> None:
        """删除并重建集合（比逐条删除更高效）。"""
        if self._available and self._client:
            try:
                self._client.delete_collection(self._collection_name)
                self._collection = self._client.get_or_create_collection(
                    name=self._collection_name,
                    metadata={"hnsw:space": "cosine"},
                )
            except Exception:
                pass

    # ========== Consolidation ==========

    async def consolidate(self, llm: Any = None) -> int:
        """容量控制：超过 10000 条时删除最旧的条目。

        不需要 LLM 参与。
        """
        if not self._available or not self._collection:
            return 0
        try:
            count = self._collection.count()
            if count > 10000:
                # 获取超出部分的 ID 并删除
                oldest = self._collection.get(
                    limit=count - 10000, include=[]
                )
                if oldest and oldest["ids"]:
                    self._collection.delete(ids=oldest["ids"])
                    return len(oldest["ids"])
        except Exception:
            pass
        return 0


def _build_chroma_filter(filters: dict) -> dict | None:
    """将 MemoryManager 的检索过滤条件转换为 ChromaDB where 子句。

    ChromaDB 的 where 格式：
        {"key": "value"}                精确匹配
        {"key": {"$gte": value}}        比较运算
        {"$and": [{...}, {...}]}       逻辑与
    """
    conds: list[dict] = []
    if "session_id" in filters:
        conds.append({"m_session_id": filters["session_id"]})
    if "memory_type" in filters:
        conds.append({"memory_type": filters["memory_type"]})
    if "min_importance" in filters:
        conds.append({"importance": {"$gte": filters["min_importance"]}})
    if not conds:
        return None
    if len(conds) == 1:
        return conds[0]
    return {"$and": conds}
