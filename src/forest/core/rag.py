from pathlib import Path

from langchain_core.documents import Document
from langchain_core.vectorstores import InMemoryVectorStore
from langchain_openai import OpenAIEmbeddings


class _TextSplitter:
    """Minimal recursive text splitter — no external dependency needed."""

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
                # force chunk at character level
                for i in range(0, len(part), self.chunk_size - self.chunk_overlap):
                    chunks.append(part[i : i + self.chunk_size])

        # merge short neighbours
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
    """Lightweight RAG engine: chunk -> embed -> store -> retrieve.

    Uses OpenAI-compatible embeddings and an in-memory vector store.
    Swap InMemoryVectorStore for a persistent store (Chroma, Pinecone, etc.)
    when you need persistence.
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
    # ingestion
    # ------------------------------------------------------------------

    def add_texts(
        self, texts: list[str], metadatas: list[dict] | None = None
    ) -> int:
        """Chunk and index a list of raw text strings. Returns number of chunks."""
        docs = self.splitter.create_documents(texts, metadatas or [{}] * len(texts))
        self.vector_store.add_documents(docs)
        self._doc_count += len(docs)
        return len(docs)

    def add_files(self, paths: list[str | Path]) -> int:
        """Load one or more text/markdown files and index their contents."""
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
        """Recursively index all files matching *glob_pattern* under *directory*."""
        total = 0
        for p in Path(directory).glob(glob_pattern):
            if p.is_file():
                total += self.add_files([p])
        return total

    # ------------------------------------------------------------------
    # retrieval
    # ------------------------------------------------------------------

    def retrieve(self, query: str, top_k: int = 5) -> list[Document]:
        """Semantic search — return top-k most relevant chunks."""
        return self.vector_store.similarity_search(query, k=top_k)

    def format_context(self, docs: list[Document]) -> str:
        """Render retrieved documents into a string ready for prompt injection."""
        if not docs:
            return ""
        parts: list[str] = []
        for i, doc in enumerate(docs, 1):
            src = doc.metadata.get("source", "")
            header = f"[{i}]" + (f" ({src})" if src else "")
            parts.append(f"{header}\n{doc.page_content}")
        return "\n\n".join(parts)

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    @property
    def doc_count(self) -> int:
        return self._doc_count

    def clear(self) -> None:
        """Drop all indexed documents."""
        self.vector_store = InMemoryVectorStore(self.embeddings)
        self._doc_count = 0
