"""FactExtractor —— 用辅助 LLM 从对话中提取语义事实。

纯提取器，不碰数据库。返回结构化事实列表供 Pipeline 消费。

提取要求 LLM 输出独立的中文事实句子，如：
  - "用户是后端工程师，主要使用 Python"
  - "用户最近在学习 Rust"
"""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage
from pydantic import BaseModel, Field

logger = logging.getLogger("haven.memory.extractor")

# ------------------------------------------------------------------
# Structured Output Schema
# ------------------------------------------------------------------


class ExtractedFact(BaseModel):
    """单条提取的事实。"""
    content: str = Field(description="独立的中文事实句子，如'用户是后端工程师'")
    importance: float = Field(
        default=0.5,
        ge=0.0, le=1.0,
        description="重要性 0-1。长期有效的偏好/背景=0.8+，一次性需求=0.3",
    )


class ExtractedFacts(BaseModel):
    """提取结果。"""
    facts: list[ExtractedFact] = Field(
        default_factory=list,
        description="提取到的事实列表，无新事实时为空",
    )


# ------------------------------------------------------------------
# Extraction Prompt
# ------------------------------------------------------------------

_EXTRACTION_PROMPT = """从以下对话中提取关于**用户**的关键事实。

规则：
1. 每条事实是一个独立、完整的中文陈述句
2. 只提取关于用户的信息（偏好、背景、技能、需求、约束），不提取 Agent 说的话
3. 如果用户没有透露新信息，返回空列表
4. importance 按以下标准：
   - 0.9：长期重要的个人信息（职业、健康状况、核心技能）
   - 0.7：有价值的偏好或背景
   - 0.5：一般性信息
   - 0.3：临时性或一次性需求

用户输入：{user_input}
Agent 回复：{agent_response}
"""


# ------------------------------------------------------------------
# FactExtractor
# ------------------------------------------------------------------


class FactExtractor:
    """语义事实提取器。

    用法::

        extractor = FactExtractor(aux_llm)
        facts = await extractor.extract(user_input, agent_response)
        # → [{"content": "用户喜欢 Python", "importance": 0.8}, ...]
    """

    def __init__(self, llm: BaseChatModel) -> None:
        # DeepSeek thinking 模式不支持 structured output，需禁用
        if getattr(llm, "_llm_type", "") == "chat-deepseek":
            extra = getattr(llm, "extra_body", None) or {}
            llm = llm.model_copy(update={
                "extra_body": {**extra, "thinking": {"type": "disabled"}},
            })
        self._llm = llm.with_structured_output(ExtractedFacts)

    async def extract(self, user_input: str, agent_response: str) -> list[dict[str, Any]]:
        """从一轮对话中提取语义事实。

        Returns:
            list[dict]: [{"content": "...", "importance": 0.8}, ...]
        """
        prompt = _EXTRACTION_PROMPT.format(
            user_input=user_input,
            agent_response=agent_response,
        )
        try:
            result: ExtractedFacts = await self._llm.ainvoke([
                HumanMessage(content=prompt),
            ])
        except Exception:
            logger.warning("事实提取 LLM 调用失败", exc_info=True)
            return []

        facts = [
            {"content": f.content, "importance": f.importance}
            for f in result.facts
        ]
        if facts:
            logger.debug("提取到 %d 条事实", len(facts))
        return facts
