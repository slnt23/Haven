import pytest

from forest.agents import ResearcherAgent


@pytest.fixture
def agent():
    return ResearcherAgent("test_researcher")


@pytest.mark.asyncio
async def test_researcher_run(agent):
    result = await agent.run("test task")
    assert "test task" in result


@pytest.mark.asyncio
async def test_researcher_step(agent):
    from langchain_core.messages import HumanMessage

    msg = HumanMessage(content="hello")
    result = await agent.step([msg])
    assert "hello" in result.content
