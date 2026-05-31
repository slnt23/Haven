from __future__ import annotations

from typing import Any

from langchain_core.messages import BaseMessage

from haven.core.base_agent import BaseAgent


class GeneralAgent(BaseAgent):
    """单一通用 agent。

    人格来自默认 skill（如 haven.md）；领域能力来自按任务匹配的按需 skill。
    不硬编码角色。
    """

    def __init__(self, name: str = "general", **kwargs: Any) -> None:
        super().__init__(name, **kwargs)

    async def run(self, task: str, **kwargs: Any) -> str:
        system_prompt = kwargs.get("system_prompt", "")
        use_rag = kwargs.get("use_rag", True)
        history = kwargs.get("history", None)
        on_demand_skills = kwargs.get("on_demand_skills", None)

        messages = self._build_messages(task, system_prompt=system_prompt, use_rag=use_rag)

        # 如有历史记录，插入到 system 与 user 消息之间
        if history:
            user_msg = messages.pop()
            messages.extend(history)
            messages.append(user_msg)

        # 追加按需 skill 的 prompt
        if on_demand_skills:
            for skill in on_demand_skills:
                if skill.prompt_extension and messages and hasattr(messages[0], "content"):
                    messages[0].content += f"\n\n{skill.prompt_extension}"

        if self._tool_instances:
            return await self._invoke_llm_with_tools(messages)
        return await self._invoke_llm(messages)

    async def step(self, messages: list[BaseMessage]) -> BaseMessage:
        if self.llm is None:
            self._init_llm()
        return await self.llm.ainvoke(messages)
