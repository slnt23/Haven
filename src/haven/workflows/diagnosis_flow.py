from __future__ import annotations

from typing import Any

from haven.agents import GeneralAgent


class DiagnosisFlow:
    def __init__(self) -> None:
        self.doctor = GeneralAgent("general")
        self.researcher = GeneralAgent("general")
        self.doctor.load_skills_from_dir()
        self.researcher.load_skills_from_dir()

    async def run(self, symptoms: str, **kwargs: Any) -> dict[str, str]:
        research = await self.researcher.run(
            f"Research medical information about: {symptoms}"
        )
        diagnosis = await self.doctor.run(
            f"Based on research, diagnose: {symptoms}\nResearch: {research}"
        )
        return {"symptoms": symptoms, "research": research, "diagnosis": diagnosis}
