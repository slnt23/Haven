"""Haven V2 Memory — 四层记忆系统。

- WorkingMemory:  滑动窗口 + LLM 摘要压缩（进程内存，不持久化）
- EpisodicMemory: 完整对话记录（SQLite），支持关键词 + 时间衰减检索
- SemanticMemory: 自然语言知识存储（SQLite），LLM 批量提取 + 合并去重
- VectorMemory:   语义向量检索（ChromaDB），embedding 相似度匹配

MemoryManager 统一编排四层生命周期:
  record_turn()   → 写入各层 + 触发批量语义提取
  retrieve()      → 四路并行检索 → MemoryContext
  consolidate()   → 后台压缩 + 衰减 + 清理
"""

from haven.memory.base import BaseMemory, MemoryContext, MemoryItem
from haven.memory.episodic import EpisodicMemory
from haven.memory.manager import MemoryManager
from haven.memory.semantic import SemanticMemory
from haven.memory.vector import VectorMemory
from haven.memory.working import WorkingMemory

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
