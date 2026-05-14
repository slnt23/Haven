from typing import Any

from langchain_core.messages import BaseMessage

from forest.core.base_agent import BaseAgent


class DoctorAgent(BaseAgent):
    async def run(self, task: str, **kwargs: Any) -> str:
        return f"[Doctor] diagnosed: {task}"

    async def step(self, messages: list[BaseMessage]) -> BaseMessage:
        msg = messages[-1]
        msg.content = f"[Doctor] examining: {msg.content}"
        return msg
