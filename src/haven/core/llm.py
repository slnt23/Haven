"""LLM 生命周期管理。

从 ``models.yaml`` 加载模型定义，根据 provider 创建对应的 LangChain 模型实例。
支持 DeepSeek（ChatDeepSeek）和 OpenAI 兼容 provider（ChatOpenAI，含阿里云 DashScope）。
API Key 通过 ``models.yaml`` 中 ``api_key_env`` 字段声明的环境变量注入。
"""

from __future__ import annotations

import logging

from langchain_core.language_models import BaseChatModel

from haven.config import get_default_model, get_model_config

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
    elif provider in ("openai", "aliyun"):
        from langchain_openai import ChatOpenAI

        model = ChatOpenAI(
            model=cfg["name"],
            api_key=cfg["api_key"],
            base_url=cfg["base_url"],
            temperature=cfg["temperature"],
            max_tokens=cfg["max_tokens"],
        )
    else:
        raise ValueError(
            f"Unknown provider: {provider}. Supported: deepseek, openai, aliyun"
        )

    return model
