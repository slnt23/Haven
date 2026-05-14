from typing import Any

from langchain_core.messages import BaseMessage

from forest.core.base_agent import BaseAgent


class DoctorAgent(BaseAgent):
    def __init__(self, name: str = "doctor", **kwargs: Any):
        super().__init__(name, **kwargs)
        self._load_agent_config()

    async def run(self, task: str, **kwargs: Any) -> str:
        system_prompt = (
            "请用中文回答。你是一名经验丰富的内科医生，请根据症状描述和已有的"
            "研究资料，给出专业的诊断意见和治疗建议。务必提醒患者咨询真实医生。"
        )
        return await self._invoke_llm(f"患者症状：{task}", system_prompt)

    async def step(self, messages: list[BaseMessage]) -> BaseMessage:
        if self.llm is None:
            self._init_llm()
        response = await self.llm.ainvoke(messages)
        return response
