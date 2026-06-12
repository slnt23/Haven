"""网络搜索工具 —— DuckDuckGo 实现。"""

from __future__ import annotations

import asyncio
from typing import Any, ClassVar

from langchain_core.tools import BaseTool
from pydantic import Field


class WebSearchTool(BaseTool):
    """搜索互联网获取最新信息。"""

    name: str = "web_search"
    description: str = (
        "Search the web for current information. "
        "Input: a search query string. "
        "Returns: formatted search results with titles, URLs, and snippets."
    )

    async def _arun(self, query: str) -> str:
        results = await self._search(query)
        return self._format(results)

    def _run(self, query: str) -> str:
        results = self._search_sync(query)
        return self._format(results)

    async def _search(self, query: str, num_results: int = 5) -> list[dict[str, str]]:
        from ddgs import DDGS

        loop = asyncio.get_running_loop()
        try:
            raw = await asyncio.wait_for(
                loop.run_in_executor(
                    None,
                    lambda: list(DDGS().text(query, max_results=num_results)),
                ),
                timeout=15,
            )
        except TimeoutError:
            raise TimeoutError("搜索超时（15s），请检查网络连接或稍后重试")
        return [
            {"title": r["title"], "url": r["href"], "snippet": r["body"]}
            for r in raw
        ]

    def _search_sync(self, query: str, num_results: int = 5) -> list[dict[str, str]]:
        import threading
        from ddgs import DDGS

        result: list[dict[str, str]] = []
        error: Exception | None = None

        def _run():
            nonlocal result, error
            try:
                raw = list(DDGS().text(query, max_results=num_results))
                result = [
                    {"title": r["title"], "url": r["href"], "snippet": r["body"]}
                    for r in raw
                ]
            except Exception as exc:
                error = exc

        thread = threading.Thread(target=_run, daemon=True)
        thread.start()
        thread.join(timeout=15)
        if thread.is_alive():
            raise TimeoutError("搜索超时（15s），请检查网络连接或稍后重试")
        if error:
            raise error
        return result

    @staticmethod
    def _format(results: list[dict[str, str]]) -> str:
        if not results:
            return "(未找到搜索结果)"
        lines: list[str] = []
        for i, r in enumerate(results, 1):
            lines.append(f"{i}. {r['title']}\n   {r['url']}\n   {r['snippet']}")
        return "\n\n".join(lines)
