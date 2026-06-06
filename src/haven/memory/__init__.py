"""Haven Memory —— 长期记忆模块。

消息持久化由 LangGraph checkpointer (SqliteSaver) 自动管理，
不需要 Haven 重复实现。

FactStore 提供 SQLite 语义事实存储 —— 这是 LangChain 没有的能力。
（LangGraph Store 是通用 KV 存储，不做自然语言事实索引/去重）
"""

from haven.memory.base import MemoryItem
from haven.memory.fact_store import FactStore

__all__ = [
    "MemoryItem",
    "FactStore",
]
