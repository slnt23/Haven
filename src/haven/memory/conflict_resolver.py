"""ConflictResolver —— 记忆冲突检测与解决。

检测同一实体的矛盾事实，通过 LLM 判断真伪并合并。
"""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage
from pydantic import BaseModel, Field

logger = logging.getLogger("haven.memory.conflict")


class ConflictCheckResult(BaseModel):
    """冲突检测结果。"""
    has_conflict: bool = Field(description="是否存在冲突")
    resolution: str = Field(default="", description="冲突解决后的合并内容")
    reasoning: str = Field(default="", description="判断理由")


_CONFLICT_PROMPT = """检测以下两条记忆事实是否矛盾：

事实 A: {fact_a}
事实 B: {fact_b}

规则：
1. 如果意思相同或互补，has_conflict=false
2. 如果确实矛盾（如 A 说"喜欢 Python"，B 说"讨厌 Python"），has_conflict=true
3. 如果矛盾，在 resolution 中给出合并后的正确版本
4. 在 reasoning 中简要说明判断依据
"""


class ConflictResolver:
    """记忆冲突检测器。

    用 LLM 检测两条事实是否矛盾，并给出合并建议。
    仅在有 LLM 可用时有效。
    """

    def __init__(self, llm: BaseChatModel | None = None) -> None:
        if llm is not None:
            self._llm = llm.with_structured_output(ConflictCheckResult)
        else:
            self._llm = None

    async def check(
        self,
        fact_a: str,
        fact_b: str,
    ) -> ConflictCheckResult:
        """检测两条事实是否冲突。

        Returns:
            ConflictCheckResult: 包含 has_conflict / resolution / reasoning。
        """
        if self._llm is None:
            return ConflictCheckResult(
                has_conflict=False,
                reasoning="No LLM available for conflict resolution",
            )

        prompt = _CONFLICT_PROMPT.format(fact_a=fact_a, fact_b=fact_b)
        try:
            result: ConflictCheckResult = await self._llm.ainvoke([
                HumanMessage(content=prompt),
            ])
            return result
        except Exception:
            logger.debug("冲突检测 LLM 调用失败", exc_info=True)
            return ConflictCheckResult(has_conflict=False)

    async def resolve_batch(
        self,
        existing_facts: list[str],
        new_fact: str,
    ) -> list[str]:
        """检查新事实与已有事实列表的冲突，返回去重后的内容列表。"""
        if self._llm is None:
            return existing_facts + [new_fact]

        resolved: list[str] = []
        merged = False

        for fact in existing_facts:
            result = await self.check(fact, new_fact)
            if result.has_conflict:
                resolved.append(result.resolution or new_fact)
                merged = True
            else:
                resolved.append(fact)

        if not merged and not any(f == new_fact for f in existing_facts):
            resolved.append(new_fact)

        return resolved
