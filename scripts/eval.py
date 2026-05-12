import asyncio
import time

from forest.agents import ResearcherAgent, CoderAgent
from forest.workflows import ResearchFlow


async def evaluate():
    agent = ResearcherAgent("eval_agent")
    start = time.perf_counter()
    result = await agent.run("test task")
    elapsed = time.perf_counter() - start
    print(f"Agent: {agent.name}, Result: {result[:50]}..., Time: {elapsed:.2f}s")

    flow = ResearchFlow()
    start = time.perf_counter()
    result = await flow.run("AI safety")
    elapsed = time.perf_counter() - start
    print(f"Flow: ResearchFlow, Keys: {list(result.keys())}, Time: {elapsed:.2f}s")


if __name__ == "__main__":
    asyncio.run(evaluate())
