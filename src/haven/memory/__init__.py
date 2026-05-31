"""Haven V2 Memory — 四层记忆系统。

- WorkingMemory:  滑动窗口 + 摘要（不持久化）
- EpisodicMemory: 完整对话记录（SQLite）
- SemanticMemory: 结构化事实 + 变更历史（SQLite）
- VectorMemory:   语义向量检索（ChromaDB）

MemoryManager 统一编排四层，提供 store/retrieve/consolidate 生命周期。
"""

from haven.memory.base import BaseMemory, MemoryItem, MemoryContext
from haven.memory.working import WorkingMemory
from haven.memory.episodic import EpisodicMemory
from haven.memory.semantic import SemanticMemory
from haven.memory.vector import VectorMemory
from haven.memory.manager import MemoryManager

__all__ = [
    "BaseMemory",
    "MemoryItem",
    "MemoryContext",
    "WorkingMemory",
    "EpisodicMemory",
    "SemanticMemory",
    "VectorMemory",
    "MemoryManager",
]
