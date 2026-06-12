"""Haven Memory —— 统一记忆层。

短期记忆：LangGraph SqliteSaver 自动管理（消息持久化）。
长期记忆：MemoryManager（FactStore + FactExtractor + VectorMemory）。

提供统一的 remember / recall / forget 接口。
ContextBuilder 通过 MemoryManager 获取上下文。
"""

from haven.memory.base import MemoryItem
from haven.memory.extractor import FactExtractor
from haven.memory.fact_store import FactStore
from haven.memory.manager import MemoryManager
from haven.memory.vector_memory import VectorMemory
from haven.memory.conflict_resolver import ConflictResolver

# Legacy alias
MemoryPipeline = MemoryManager

__all__ = [
    "MemoryItem",
    "FactStore",
    "FactExtractor",
    "MemoryManager",
    "MemoryPipeline",
    "VectorMemory",
    "ConflictResolver",
]
