import pytest

from haven.agents import GeneralAgent


@pytest.fixture
def agent():
    a = GeneralAgent("general")
    a.load_skills_from_dir()
    return a


@pytest.mark.asyncio
async def test_general_run(agent):
    result = await agent.run("reply with: ok")
    assert len(result) > 0


@pytest.mark.asyncio
async def test_general_step(agent):
    from langchain_core.messages import HumanMessage

    msg = HumanMessage(content="reply with one word: ok")
    result = await agent.step([msg])
    assert len(result.content) > 0
