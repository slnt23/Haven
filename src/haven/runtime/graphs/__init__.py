"""预定义工作流图。"""

from __future__ import annotations

from langgraph.checkpoint.memory import MemorySaver


def create_checkpointer() -> MemorySaver:
    """创建内存 checkpoint。后续可切换为 SqliteSaver。"""
    return MemorySaver()
