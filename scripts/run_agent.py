import asyncio
import sys

from forest.agents import OrchestratorAgent, ResearcherAgent, CoderAgent, DoctorAgent
from forest.workflows import DiagnosisFlow


async def main():
    args = sys.argv[1:]
    if args and args[0] == "doctor":
        task = " ".join(args[1:]) or "headache and fever"
        flow = DiagnosisFlow()
        result = await flow.run(task)
        for key, val in result.items():
            print(f"[{key}] {val}")
        return

    task = " ".join(args) or "Explore the concept of multi-agent systems"
    orchestrator = OrchestratorAgent()
    researcher = ResearcherAgent("researcher")
    coder = CoderAgent("coder")
    orchestrator.register_agent("researcher", researcher)
    orchestrator.register_agent("coder", coder)

    result = await orchestrator.run(task)
    print(result)


if __name__ == "__main__":
    asyncio.run(main())
