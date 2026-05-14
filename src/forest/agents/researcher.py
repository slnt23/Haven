from typing import Any

from langchain_core.messages import BaseMessage

from forest.core.base_agent import BaseAgent


class ResearcherAgent(BaseAgent):
    def __init__(self, name: str = "researcher", **kwargs: Any):
        super().__init__(name, **kwargs)
        self._load_agent_config()

    async def run(self, task: str, **kwargs: Any) -> str:
        system_prompt = (
            "请用中文回答。根据你的角色和专业知识，对以下课题进行深入研究和分析，"
            "提供准确、全面的信息。"
        )
        return await self._invoke_llm(f"研究课题：{task}", system_prompt)

    async def step(self, messages: list[BaseMessage]) -> BaseMessage:
        if self.llm is None:
            self._init_llm()
        response = await self.llm.ainvoke(messages)
        return response
