"""PromptBuilder — system prompt 最终组装。

简化后不再直接访问 MemoryManager / SkillRegistry / Workflow。
只接收 ContextManager.build() 返回的 ContextBundle，进行最终校验和格式化。
"""

from __future__ import annotations

from haven.core.context import ContextBundle, TokenBudget


class PromptBuilder:
    """System prompt 组装器（薄层）。

    职责缩减为：
      1. 接收 ContextManager.build() 返回的 ContextBundle
      2. 最终 token 预算校验
      3. 添加系统级包装（如有需要）

    用法::

        cm = ContextManager(memory=runtime.memory)
        bundle = cm.build(personality_skills=[...], domain_skills=[...])
        builder = PromptBuilder(max_system_tokens=4000)
        system_prompt = builder.build(bundle)
    """

    def __init__(self, max_system_tokens: int = 4000):
        self._budget = TokenBudget(max_system_tokens)

    def build(self, context: ContextBundle | str) -> str:
        """对 ContextManager.build() 的结果进行最终校验。

        Args:
            context: ContextBundle（ContextManager.build() 的输出）
                     或纯字符串（兼容旧调用）。

        Returns:
            最终 system prompt 字符串。
        """
        if isinstance(context, str):
            prompt = context
        else:
            prompt = context.system_prompt

        if not prompt:
            return ""

        if not self._budget.fits(prompt):
            # 硬截断——正常路径下 ContextAssembler 已处理预算
            max_chars = self._budget.max_tokens * 3
            prompt = prompt[:max_chars] + "\n...[已截断]"

        return prompt
