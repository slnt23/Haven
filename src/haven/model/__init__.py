"""Model 层 —— LLM 抽象。

Agent 仅依赖 LLMClient 接口，不直接接触 LangChain BaseChatModel。
ModelFactory 根据 ModelConfig 创建正确的客户端实例。

提供：
  - LLMClient —— 包装 LangChain BaseChatModel 的统一接口
  - ModelFactory —— 从 AppConfig 创建 LLMClient
"""

from haven.model.llm import LLMClient, ModelFactory

__all__ = [
    "LLMClient",
    "ModelFactory",
]
