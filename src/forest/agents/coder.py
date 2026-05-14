from typing import Any

from langchain_core.messages import BaseMessage

from forest.core.base_agent import BaseAgent


class CoderAgent(BaseAgent):
    def __init__(self, name: str = "coder", **kwargs: Any):
        super().__init__(name, **kwargs)
        self._load_agent_config()

    async def run(self, task: str, **kwargs: Any) -> str:
        system_prompt = (
            "请用中文回答。你是一名资深软件工程师，请根据需求编写清晰、高效、"
            "可运行的代码，包含必要的说明。"
        )
        return await self._invoke_llm(f"开发需求：{task}", system_prompt)

    async def step(self, messages: list[BaseMessage]) -> BaseMessage:
        if self.llm is None:
            self._init_llm()
        response = await self.llm.ainvoke(messages)
        return response
