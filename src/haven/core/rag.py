from pathlib import Path

from langchain_core.documents import Document
from langchain_core.vectorstores import InMemoryVectorStore
from langchain_openai import OpenAIEmbeddings


class _TextSplitter:
    """极简递归文本分割器——无需外部依赖。"""

    def __init__(self, chunk_size: int = 1000, chunk_overlap: int = 200):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self._separators = ["\n\n", "\n", "。", ". ", " ", ""]

    def _split(self, text: str, separators: list[str]) -> list[str]:
        sep = separators[0]
        remaining = separators[1:]

        if sep:
            parts = text.split(sep)
        else:
            parts = list(text)

        chunks: list[str] = []
        for part in parts:
            part = part.strip()
            if not part:
                continue

            if len(part) <= self.chunk_size:
                chunks.append(part)
            elif remaining:
                chunks.extend(self._split(part, remaining))
            else:
                # 字符级强制切块
                for i in range(0, len(part), self.chunk_size - self.chunk_overlap):
                    chunks.append(part[i : i + self.chunk_size])

        # 合并过短的相邻块
        merged_chunks: list[str] = []
        for c in chunks:
            if (
                merged_chunks
                and len(merged_chunks[-1]) + len(c) < self.chunk_size
            ):
                merged_chunks[-1] = f"{merged_chunks[-1]}\n{c}"
            else:
                merged_chunks.append(c)
        return merged_chunks

    def create_documents(
        self, texts: list[str], metadatas: list[dict]
    ) -> list[Document]:
        docs: list[Document] = []
        for text, meta in zip(texts, metadatas):
            for chunk in self._split(text, list(self._separators)):
                docs.append(Document(page_content=chunk, metadata=dict(meta)))
        return docs


class RAGEngine:
    """轻量级 RAG 引擎：分块 → 嵌入 → 存储 → 检索。

    使用 OpenAI 兼容嵌入模型和内存向量存储。
    需要持久化时可替换为 Chroma、Pinecone 等持久存储。
    """

    def __init__(
        self,
        embedding_model: str = "text-embedding-3-small",
        embedding_api_key: str = "",
        embedding_base_url: str = "",
        chunk_size: int = 1000,
        chunk_overlap: int = 200,
    ):
        kw: dict = {"model": embedding_model, "api_key": embedding_api_key}
        if embedding_base_url:
            kw["base_url"] = embedding_base_url
        self.embeddings = OpenAIEmbeddings(**kw)

        self.vector_store = InMemoryVectorStore(self.embeddings)
        self.splitter = _TextSplitter(chunk_size=chunk_size, chunk_overlap=chunk_overlap)
        self._doc_count = 0

    # ------------------------------------------------------------------
    # 数据导入
    # ------------------------------------------------------------------

    def add_texts(
        self, texts: list[str], metadatas: list[dict] | None = None
    ) -> int:
        """将原始文本列表分块并索引。返回分块数。"""
        docs = self.splitter.create_documents(texts, metadatas or [{}] * len(texts))
        self.vector_store.add_documents(docs)
        self._doc_count += len(docs)
        return len(docs)

    def add_files(self, paths: list[str | Path]) -> int:
        """加载一个或多个文本/markdown 文件并索引其内容。"""
        total = 0
        for path in paths:
            p = Path(path)
            if not p.exists():
                continue
            text = p.read_text(encoding="utf-8")
            total += self.add_texts([text], [{"source": str(p)}])
        return total

    def add_directory(
        self, directory: str | Path, glob_pattern: str = "**/*.md"
    ) -> int:
        """递归索引 *directory* 下匹配 *glob_pattern* 的所有文件。"""
        total = 0
        for p in Path(directory).glob(glob_pattern):
            if p.is_file():
                total += self.add_files([p])
        return total

    # ------------------------------------------------------------------
    # 检索
    # ------------------------------------------------------------------

    def retrieve(self, query: str, top_k: int = 5) -> list[Document]:
        """语义搜索——返回 top-k 最相关片段。"""
        return self.vector_store.similarity_search(query, k=top_k)

    def format_context(self, docs: list[Document]) -> str:
        """将检索到的文档渲染为可注入 prompt 的字符串。"""
        if not docs:
            return ""
        parts: list[str] = []
        for i, doc in enumerate(docs, 1):
            src = doc.metadata.get("source", "")
            header = f"[{i}]" + (f" ({src})" if src else "")
            parts.append(f"{header}\n{doc.page_content}")
        return "\n\n".join(parts)

    # ------------------------------------------------------------------
    # 辅助方法
    # ------------------------------------------------------------------

    @property
    def doc_count(self) -> int:
        return self._doc_count

    def clear(self) -> None:
        """清除所有已索引文档。"""
        self.vector_store = InMemoryVectorStore(self.embeddings)
        self._doc_count = 0
