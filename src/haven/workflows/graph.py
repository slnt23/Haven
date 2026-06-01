"""Workflow 图工具 — LangGraph StateGraph 封装。

使用 LangGraph MemorySaver 做 checkpoint。
如需 SQLite 持久化：pip install langgraph-checkpoint-sqlite，然后将 SqliteSaver 替换 MemorySaver。
"""

from __future__ import annotations

from langgraph.checkpoint.memory import MemorySaver
from langgraph.constants import END
from langgraph.graph import StateGraph


def create_checkpointer() -> MemorySaver:
    """创建内存 checkpoint。后续可切换为 SqliteSaver。"""
    return MemorySaver()


__all__ = ["create_checkpointer", "END", "StateGraph"]
