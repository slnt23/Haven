from typing import Any

from langchain_core.messages import BaseMessage

from forest.core.base_agent import BaseAgent


class OrchestratorAgent(BaseAgent):
    def __init__(self, name: str = "orchestrator", llm: Any = None):
        super().__init__(name, llm)
        self.sub_agents: dict[str, BaseAgent] = {}

    def register_agent(self, name: str, agent: BaseAgent) -> None:
        self.sub_agents[name] = agent

    async def run(self, task: str, **kwargs: Any) -> str:
        results: list[str] = []
        for name, agent in self.sub_agents.items():
            result = await agent.run(f"{task} (subtask from orchestrator)")
            results.append(f"[{name}] {result}")
        return "\n".join(results)

    async def step(self, messages: list[BaseMessage]) -> BaseMessage:
        msg = messages[-1]
        msg.content = f"[Orchestrator] delegating: {msg.content}"
        return msg
