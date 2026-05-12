import asyncio
import sys

from forest.agents import OrchestratorAgent, ResearcherAgent, CoderAgent


async def main():
    task = " ".join(sys.argv[1:]) or "Explore the concept of multi-agent systems"
    orchestrator = OrchestratorAgent()
    researcher = ResearcherAgent("researcher")
    coder = CoderAgent("coder")
    orchestrator.register_agent("researcher", researcher)
    orchestrator.register_agent("coder", coder)

    result = await orchestrator.run(task)
    print(result)


if __name__ == "__main__":
    asyncio.run(main())
