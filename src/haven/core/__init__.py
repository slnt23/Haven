"""Core 模块 — 框架基础组件。

提供 LLM 生命周期管理和组件注册表。
"""

from .llm import create_llm

__all__ = ["create_llm"]
