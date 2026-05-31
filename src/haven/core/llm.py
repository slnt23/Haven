"""LLM 生命周期管理。

从 ``models.yaml`` 加载配置，创建对应的 LangChain 模型实例。
支持 DeepSeek 和 OpenAI 兼容 provider，可通过环境变量注入 API Key。
"""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.language_models import BaseChatModel

from haven.config import get_model_config, get_default_model

logger = logging.getLogger("haven.core.llm")


def create_llm(model_name: str | None = None) -> BaseChatModel:
    """从 ``models.yaml`` 加载配置并创建 LangChain 模型实例。

    Args:
        model_name: 模型名（对应 models.yaml 中 models 键）。
                    为 None 时使用 default_model。

    Returns:
        已配置的 LangChain BaseChatModel 实例。

    Raises:
        ValueError: provider 不在支持的列表中。
        KeyError: model_name 在 models.yaml 中不存在。
    """
    model_name = model_name or get_default_model()
    cfg = get_model_config(model_name)
    provider = cfg["provider"]

    if provider == "deepseek":
        from langchain_deepseek import ChatDeepSeek

        model = ChatDeepSeek(
            model=cfg["name"],
            api_key=cfg["api_key"],
            api_base=cfg["base_url"],
            temperature=cfg["temperature"],
            max_tokens=cfg["max_tokens"],
        )
    elif provider == "openai":
        from langchain_openai import ChatOpenAI

        model = ChatOpenAI(
            model=cfg["name"],
            api_key=cfg["api_key"],
            base_url=cfg["base_url"],
            temperature=cfg["temperature"],
            max_tokens=cfg["max_tokens"],
        )
    else:
        raise ValueError(f"Unknown provider: {provider}")

    return model


def bind_tools(llm: BaseChatModel, tools: list[Any]) -> BaseChatModel:
    """对 LLM 执行 ``bind_tools()``。

    Args:
        llm: LangChain 模型实例。
        tools: BaseTool 列表。空列表时返回原 llm。

    Returns:
        已绑定工具的模型（或原模型，如果 tools 为空）。
    """
    if not tools:
        return llm
    return llm.bind_tools(tools)
