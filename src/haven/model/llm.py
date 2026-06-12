"""LLM 抽象层 —— LLMClient 包装器 + ModelFactory。

Agent 不直接接触 BaseChatModel。所有模型访问通过 LLMClient，
ModelFactory 负责按 provider 类型创建正确的客户端。
"""

from __future__ import annotations

import logging
from typing import Any, AsyncIterator

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage
from langchain_core.tools import BaseTool

from haven.config.schema import AppConfig, ModelConfig
from haven.kernel.errors import ModelError

logger = logging.getLogger("haven.model")


class LLMClient:
    """轻量包装 LangChain BaseChatModel，Agent 唯一直面的 LLM 接口。

    封装 provider 差异，Agent 无需关心底层是 DeepSeek / OpenAI / 自定义。
    """

    def __init__(self, model: BaseChatModel, config: ModelConfig) -> None:
        self._model = model
        self._config = config

    # ------------------------------------------------------------------
    # 标识
    # ------------------------------------------------------------------

    @property
    def model_name(self) -> str:
        return self._config.name

    @property
    def provider(self) -> str:
        return self._config.provider

    @property
    def temperature(self) -> float:
        return self._config.temperature

    @property
    def max_tokens(self) -> int:
        return self._config.max_tokens

    # ------------------------------------------------------------------
    # 核心方法 — 委托给 LangChain BaseChatModel
    # ------------------------------------------------------------------

    async def ainvoke(
        self,
        messages: list[BaseMessage],
        **kwargs: Any,
    ) -> Any:
        """非流式调用 LLM，返回完整响应消息。"""
        return await self._model.ainvoke(messages, **kwargs)

    async def astream(
        self,
        messages: list[BaseMessage],
        **kwargs: Any,
    ) -> AsyncIterator[Any]:
        """流式调用 LLM，逐 chunk yield。"""
        async for chunk in self._model.astream(messages, **kwargs):
            yield chunk

    def bind_tools(
        self,
        tools: list[BaseTool] | list[dict],
    ) -> LLMClient:
        """绑定工具集，返回新的 LLMClient（原实例不变）。

        委托给 LangChain bind_tools()，将工具注入 Function Calling schema。
        """
        bound = self._model.bind_tools(tools)
        return LLMClient(bound, self._config)

    def with_structured_output(
        self,
        schema: type,
        **kwargs: Any,
    ) -> Any:
        """返回支持结构化输出的可运行对象。

        委托给 LangChain with_structured_output()，
        Planner 用它生成 ExecutionPlan。
        """
        return self._model.with_structured_output(schema, **kwargs)

    # ------------------------------------------------------------------
    # 原始访问（仅内部使用）
    # ------------------------------------------------------------------

    @property
    def _raw(self) -> BaseChatModel:
        """获取底层 LangChain 模型。仅供 Infrastructure 层使用。"""
        return self._model


# ============================================================================
# ModelFactory
# ============================================================================


class ModelFactory:
    """从 AppConfig 创建 LLMClient 实例。

    按 ModelConfig.provider 类型路由到正确的 LangChain 客户端：
      - deepseek → ChatDeepSeek
      - openai / aliyun → ChatOpenAI (OpenAI 兼容)

    Usage::

        factory = ModelFactory(app_config)
        default_client = factory.create()
        aux_client = factory.create(app_config.auxiliary_model)
    """

    # provider → 工厂函数
    _builders: dict[str, Any] = {}

    def __init__(self, config: AppConfig) -> None:
        self._config = config

    # ------------------------------------------------------------------
    # 公开 API
    # ------------------------------------------------------------------

    def create(self, model_name: str | None = None) -> LLMClient:
        """创建 LLMClient 实例。

        Args:
            model_name: 模型名（对应 models.yaml 中的键）。
                       为 None 时使用 AppConfig.default_model。

        Returns:
            已配置的 LLMClient。

        Raises:
            ModelError: model_name 不存在或 provider 不支持。
        """
        name = model_name or self._config.default_model
        model_cfg = self._config.models.get(name)
        if model_cfg is None:
            raise ModelError(
                f"Model '{name}' not found. Available: {list(self._config.models.keys())}"
            )

        provider = model_cfg.provider
        raw = self._build_raw(model_cfg)

        if raw is None:
            raise ModelError(
                f"Unsupported provider '{provider}' for model '{name}'. "
                f"Supported: deepseek, openai, aliyun"
            )

        logger.info("Created LLMClient: %s (provider=%s)", name, provider)
        return LLMClient(raw, model_cfg)

    def get_default(self) -> LLMClient:
        """创建默认模型的 LLMClient。"""
        return self.create(self._config.default_model)

    def get_auxiliary(self) -> LLMClient:
        """创建辅助模型的 LLMClient，用于后台任务（记忆提取等）。"""
        return self.create(self._config.auxiliary_model)

    def list_models(self) -> list[str]:
        """返回所有可用模型名列表。"""
        return list(self._config.models.keys())

    # ------------------------------------------------------------------
    # Provider 路由
    # ------------------------------------------------------------------

    def _build_raw(self, cfg: ModelConfig) -> BaseChatModel | None:
        provider = cfg.provider

        if provider == "deepseek":
            from langchain_deepseek import ChatDeepSeek

            return ChatDeepSeek(
                model=cfg.name,
                api_key=cfg.api_key,
                api_base=cfg.base_url,
                temperature=cfg.temperature,
                max_tokens=cfg.max_tokens,
            )

        if provider in ("openai", "aliyun"):
            from langchain_openai import ChatOpenAI

            return ChatOpenAI(
                model=cfg.name,
                api_key=cfg.api_key,
                base_url=cfg.base_url,
                temperature=cfg.temperature,
                max_tokens=cfg.max_tokens,
            )

        # Unknown provider — 返回 None 由调用方处理
        return None
