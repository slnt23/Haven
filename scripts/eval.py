import asyncio
import time

from forest.agents import GeneralAgent
from forest.tools import MedicalKnowledgeTool
from forest.workflows import ResearchFlow, DiagnosisFlow


async def evaluate() -> None:
    agent = GeneralAgent("general")
    agent.load_skills_from_dir()
    start = time.perf_counter()
    result = await agent.run("test task")
    elapsed = time.perf_counter() - start
    print(f"Agent: {agent.name}, Result: {result[:50]}..., Time: {elapsed:.2f}s")

    flow = ResearchFlow()
    start = time.perf_counter()
    result = await flow.run("AI safety")
    elapsed = time.perf_counter() - start
    print(f"Flow: ResearchFlow, Keys: {list(result.keys())}, Time: {elapsed:.2f}s")

    tool = MedicalKnowledgeTool()
    start = time.perf_counter()
    result = await tool("lookup", "headache")
    elapsed = time.perf_counter() - start
    print(f"MedicalKB lookup result:\n{result}\nTime: {elapsed:.2f}s")

    flow = DiagnosisFlow()
    start = time.perf_counter()
    result = await flow.run("chest pain and fatigue")
    elapsed = time.perf_counter() - start
    print(f"Flow: DiagnosisFlow, Keys: {list(result.keys())}, Time: {elapsed:.2f}s")


if __name__ == "__main__":
    asyncio.run(evaluate())
