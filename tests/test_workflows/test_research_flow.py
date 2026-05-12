import pytest

from forest.workflows import ResearchFlow


@pytest.fixture
def flow():
    return ResearchFlow()


@pytest.mark.asyncio
async def test_research_flow(flow):
    result = await flow.run("AI Agents")
    assert "research" in result
    assert "summary" in result
