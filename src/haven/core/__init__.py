"""Core 模块 — 框架基础组件。

提供 LLM 生命周期管理、运行时状态容器和组件注册表。
对外暴露 ``create_llm`` 工厂和 ``RuntimeState`` 会话状态。
"""

from .llm import create_llm
from .state import RuntimeState

__all__ = ["create_llm", "RuntimeState"]
