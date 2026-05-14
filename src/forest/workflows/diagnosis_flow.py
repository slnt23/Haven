from typing import Any

from forest.agents import DoctorAgent, ResearcherAgent
from forest.config import settings


class DiagnosisFlow:
    def __init__(self):
        self.doctor = DoctorAgent("doctor")
        self.researcher = ResearcherAgent("researcher")

    async def run(self, symptoms: str, **kwargs: Any) -> dict[str, str]:
        research = await self.researcher.run(f"Research medical information about: {symptoms}")
        diagnosis = await self.doctor.run(f"Based on research, diagnose: {symptoms}\nResearch: {research}")
        return {"symptoms": symptoms, "research": research, "diagnosis": diagnosis}
