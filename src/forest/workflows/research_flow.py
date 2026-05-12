from typing import Any

from forest.agents import OrchestratorAgent, ResearcherAgent, CoderAgent
from forest.config import settings


class ResearchFlow:
    def __init__(self):
        self.orchestrator = OrchestratorAgent()
        self.researcher = ResearcherAgent("researcher")
        self.coder = CoderAgent("coder")
        self.orchestrator.register_agent("researcher", self.researcher)
        self.orchestrator.register_agent("coder", self.coder)

    async def run(self, topic: str, **kwargs: Any) -> dict[str, str]:
        research = await self.researcher.run(f"Research: {topic}")
        summary = await self.coder.run(f"Summarize research: {research}")
        return {"research": research, "summary": summary}
