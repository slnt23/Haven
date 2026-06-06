"""预定义工作流图。

每个工作流通过 WorkflowRegistry 注册，Coordinator 的 LLM 规划时
从菜单中选取匹配的工作流名称，Dispatcher 负责编译和执行。
"""

from __future__ import annotations

from langgraph.checkpoint.memory import MemorySaver


def create_checkpointer() -> MemorySaver:
    """创建内存 checkpointer。后续可切换为 SqliteSaver。"""
    return MemorySaver()
