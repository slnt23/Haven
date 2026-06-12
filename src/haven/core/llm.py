"""LLM 工厂 —— 委托给新 ModelFactory 的兼容层。

Phase 7 (Agent) 后移除此文件，代码直接使用 ModelFactory。
"""

from __future__ import annotations

import logging

from langchain_core.language_models import BaseChatModel

from haven.config import load_config
from haven.model.llm import ModelFactory

logger = logging.getLogger("haven.core.llm")

_factory: ModelFactory | None = None


def _get_factory() -> ModelFactory:
    global _factory
    if _factory is None:
        _factory = ModelFactory(load_config())
    return _factory


def create_llm(model_name: str | None = None) -> BaseChatModel:
    """创建 LangChain 模型实例（兼容旧代码）。

    Args:
        model_name: 模型名，为 None 时使用默认模型。

    Returns:
        已配置的 LangChain BaseChatModel。

    Raises:
        ModelError: 模型不存在或 provider 不支持。
    """
    client = _get_factory().create(model_name)
    return client._raw
