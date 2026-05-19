import asyncio
import sys

from forest.agents import GeneralAgent, OrchestratorAgent
from forest.workflows import DiagnosisFlow


async def main() -> None:
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
    agent_a = GeneralAgent("general")
    agent_b = GeneralAgent("general")
    agent_a.load_skills_from_dir()
    agent_b.load_skills_from_dir()
    orchestrator.register_agent("agent_a", agent_a)
    orchestrator.register_agent("agent_b", agent_b)

    result = await orchestrator.run(task)
    print(result)


if __name__ == "__main__":
    asyncio.run(main())
