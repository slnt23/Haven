from __future__ import annotations

from typing import Any

from haven.agents import GeneralAgent, OrchestratorAgent


class DevFlow:
    def __init__(self) -> None:
        self.orchestrator = OrchestratorAgent()
        self.researcher = GeneralAgent("general")
        self.coder = GeneralAgent("general")
        self.researcher.load_skills_from_dir()
        self.coder.load_skills_from_dir()
        self.orchestrator.register_agent("researcher", self.researcher)
        self.orchestrator.register_agent("coder", self.coder)

    async def run(self, requirement: str, **kwargs: Any) -> dict[str, str]:
        plan = await self.researcher.run(f"Plan implementation for: {requirement}")
        code = await self.coder.run(f"Implement: {plan}")
        return {"plan": plan, "code": code}
