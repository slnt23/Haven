"""PromptBuilder — 统一 system prompt 组装。

负责按优先级合并：
  1. 人格 skill (default=true)
  2. 领域 skill (Planner 激活)
  3. 长期记忆上下文
  4. RAG 检索上下文

控制 token 预算，超出时从低优先级裁剪。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from haven.skills.base_skill import BaseSkill


class TokenBudget:
    """简单的 token 预算估算器。

    按 1 token ≈ 3 个字符估算（中文约 1 token ≈ 1.5 字符）。
    """

    def __init__(self, max_tokens: int = 4000):
        self.max_tokens = max_tokens

    def estimate(self, text: str) -> int:
        """估算文本的 token 数。"""
        if not text:
            return 0
        chinese_chars = sum(1 for c in text if "一" <= c <= "鿿")
        other_chars = len(text) - chinese_chars
        return int(chinese_chars * 1.5 + other_chars / 3)

    def fits(self, text: str) -> bool:
        return self.estimate(text) <= self.max_tokens


class PromptBuilder:
    """统一 system prompt 组装器。

    用法::

        builder = PromptBuilder(max_system_tokens=4000)
        system = builder.build(
            personality_skills=[haven_skill],
            domain_skills=[coder_skill],
            memory_context="[长期记忆] ...",
            rag_context="[参考知识] ...",
        )
    """

    def __init__(self, max_system_tokens: int = 4000):
        self._budget = TokenBudget(max_system_tokens)

    def build(
        self,
        personality_skills: list["BaseSkill"] | None = None,
        domain_skills: list["BaseSkill"] | None = None,
        memory_context: str = "",
        rag_context: str = "",
    ) -> str:
        """按优先级组装 system prompt。

        优先级：人格 > 领域 > 记忆 > RAG
        预算不足时从 RAG 开始裁剪。
        """
        sections: list[tuple[int, str]] = []

        # 1. 人格 skill — 最高优先级
        for skill in (personality_skills or []):
            prompt = getattr(skill, "prompt_extension", "") or skill.prompt
            if prompt.strip():
                sections.append((0, prompt.strip()))

        # 2. 领域 skill
        for skill in (domain_skills or []):
            prompt = getattr(skill, "prompt_extension", "") or skill.prompt
            if prompt.strip():
                sections.append((1, prompt.strip()))

        # 3. 长期记忆
        if memory_context.strip():
            sections.append((2, memory_context.strip()))

        # 4. RAG
        if rag_context.strip():
            sections.append((3, rag_context.strip()))

        # 排序 + 预算裁剪
        sections.sort(key=lambda x: x[0])

        result_parts: list[str] = []
        used = 0

        for _, text in sections:
            est = self._budget.estimate(text)
            if used + est <= self._budget.max_tokens:
                result_parts.append(text)
                used += est
            else:
                # 超出预算：尝试截断当前段
                remaining = self._budget.max_tokens - used
                if remaining > 100:
                    truncated = text[: remaining * 3] + "\n...[已截断]"
                    result_parts.append(truncated)
                break

        return "\n\n".join(result_parts)
