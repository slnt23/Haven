from typing import Any

from langchain_core.messages import BaseMessage

from forest.core.base_agent import BaseAgent


class CoderAgent(BaseAgent):
    async def run(self, task: str, **kwargs: Any) -> str:
        return f"[Coder] implemented: {task}"

    async def step(self, messages: list[BaseMessage]) -> BaseMessage:
        msg = messages[-1]
        msg.content = f"[Coder] implementing: {msg.content}"
        return msg
