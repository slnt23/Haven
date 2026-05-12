from typing import Any

from forest.agents import OrchestratorAgent, ResearcherAgent, CoderAgent


class DevFlow:
    def __init__(self):
        self.orchestrator = OrchestratorAgent()
        self.researcher = ResearcherAgent("researcher")
        self.coder = CoderAgent("coder")
        self.orchestrator.register_agent("researcher", self.researcher)
        self.orchestrator.register_agent("coder", self.coder)

    async def run(self, requirement: str, **kwargs: Any) -> dict[str, str]:
        plan = await self.researcher.run(f"Plan implementation for: {requirement}")
        code = await self.coder.run(f"Implement: {plan}")
        return {"plan": plan, "code": code}
