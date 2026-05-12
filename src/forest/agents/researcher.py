from typing import Any

from langchain_core.messages import BaseMessage

from forest.core.base_agent import BaseAgent


class ResearcherAgent(BaseAgent):
    async def run(self, task: str, **kwargs: Any) -> str:
        return f"[Researcher] researched: {task}"

    async def step(self, messages: list[BaseMessage]) -> BaseMessage:
        msg = messages[-1]
        msg.content = f"[Researcher] processing: {msg.content}"
        return msg
