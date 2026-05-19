from forest.core.tool_registry import ToolRegistry


@ToolRegistry.register("rag_search")
class RAGSearchTool:
    """Explicit knowledge-base search tool — the LLM can call this when it needs
    to look up domain knowledge that wasn't already injected into context."""

    def __init__(self, rag_engine: object | None = None):
        self._rag = rag_engine

    def set_engine(self, rag_engine: object) -> None:
        self._rag = rag_engine

    async def __call__(self, query: str, top_k: int = 5) -> str:
        if self._rag is None:
            return "[RAG] 知识库未配置，请先加载文档。"

        docs = self._rag.retrieve(query, top_k=top_k)  # type: ignore[union-attr]
        if not docs:
            return "[RAG] 未找到相关知识。"
        return self._rag.format_context(docs)  # type: ignore[union-attr]
