from haven.config import settings


class WebSearchTool:
    def __init__(self):
        self.api_key = settings.web_search_api_key
        self.engine = settings.web_search_engine

    async def search(self, query: str, num_results: int = 5) -> list[dict[str, str]]:
        return [
            {"title": "example", "url": "https://example.com", "snippet": f"Result for: {query}"}
        ]

    async def __call__(self, query: str) -> str:
        results = await self.search(query)
        return "\n".join(r["snippet"] for r in results)
