import pytest

from haven.tools import WebSearchTool


@pytest.fixture
def tool():
    return WebSearchTool()


@pytest.mark.asyncio
async def test_search(tool):
    results = await tool.search("pytest")
    assert len(results) > 0
