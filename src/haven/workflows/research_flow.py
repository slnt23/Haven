from __future__ import annotations

from typing import Any

from haven.agents import GeneralAgent, OrchestratorAgent


class ResearchFlow:
    def __init__(self) -> None:
        self.orchestrator = OrchestratorAgent()
        self.researcher = GeneralAgent("general")
        self.coder = GeneralAgent("general")
        self.researcher.load_skills_from_dir()
        self.coder.load_skills_from_dir()
        self.orchestrator.register_agent("researcher", self.researcher)
        self.orchestrator.register_agent("coder", self.coder)

    async def run(self, topic: str, **kwargs: Any) -> dict[str, str]:
        research = await self.researcher.run(f"Research: {topic}")
        summary = await self.coder.run(f"Summarize research: {research}")
        return {"research": research, "summary": summary}
