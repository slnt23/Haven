"""网络搜索工具 —— DuckDuckGo 实现。

LLM 调用方式：
  - 工具名: web_search
  - 输入: 搜索关键词字符串
  - 输出: 格式化的搜索结果文本（标题 + URL + 摘要）
"""

from __future__ import annotations

import asyncio
from typing import Any

from haven.tools.base import HavenTool
from haven.tools.metadata import ToolMetadata


class WebSearchTool(HavenTool):
    """搜索互联网获取最新信息。

    LLM 通过 Function Calling 自动调用，无需框架层介入选择。
    """

    name: str = "web_search"
    description: str = (
        "Search the web for current information. "
        "Input: a search query string. "
        "Returns: formatted search results with titles, URLs, and snippets."
    )
    metadata: ToolMetadata = ToolMetadata(provider="builtin")

    # ------------------------------------------------------------------
    # LangChain BaseTool 接口
    # ------------------------------------------------------------------

    async def _arun(self, query: str) -> str:
        """异步执行搜索并格式化为文本。"""
        results = await self._search(query)
        return self._format(results)

    def _run(self, query: str) -> str:
        """同步执行搜索（回退路径）。"""
        results = self._search_sync(query)
        return self._format(results)

    # ------------------------------------------------------------------
    # 搜索实现
    # ------------------------------------------------------------------

    async def _search(self, query: str, num_results: int = 5) -> list[dict[str, str]]:
        """异步搜索 —— DuckDuckGo（15 秒超时）。"""
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
        """同步搜索 —— DuckDuckGo（15 秒超时）。"""
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

    # ------------------------------------------------------------------
    # 格式化
    # ------------------------------------------------------------------

    @staticmethod
    def _format(results: list[dict[str, str]]) -> str:
        if not results:
            return "(未找到搜索结果)"
        lines: list[str] = []
        for i, r in enumerate(results, 1):
            lines.append(f"{i}. {r['title']}\n   {r['url']}\n   {r['snippet']}")
        return "\n\n".join(lines)
