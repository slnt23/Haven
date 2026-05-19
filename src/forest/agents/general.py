from __future__ import annotations

from typing import Any

from langchain_core.messages import BaseMessage

from forest.core.base_agent import BaseAgent


class GeneralAgent(BaseAgent):
    """A single general-purpose agent.

    Personality comes from default skills (e.g. haven.md); domain expertise
    comes from on-demand skills matched per task.  No hardcoded roles.
    """

    def __init__(self, name: str = "general", **kwargs: Any) -> None:
        super().__init__(name, **kwargs)

    async def run(self, task: str, **kwargs: Any) -> str:
        return await self._invoke_llm(task, system_prompt=kwargs.get("system_prompt", ""))

    async def step(self, messages: list[BaseMessage]) -> BaseMessage:
        if self.llm is None:
            self._init_llm()
        return await self.llm.ainvoke(messages)
