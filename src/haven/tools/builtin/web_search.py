"""网络搜索工具（占位实现）。

当前为占位版本，返回示例结果。后续可替换为真实的搜索引擎 API。

LLM 调用方式：
  - 工具名: web_search
  - 输入: 搜索关键词字符串
  - 输出: 格式化的搜索结果文本
"""

from __future__ import annotations

from typing import Any

from haven.tools.base import HavenTool
from haven.tools.metadata import ToolMetadata


class WebSearchTool(HavenTool):
    """搜索互联网获取最新信息。

    LLM 通过 Function Calling 自动调用，无需框架层介入选择。
    """

    # 工具标识 —— LLM 根据这两个字段决定是否调用
    name: str = "web_search"
    description: str = (
        "Search the web for current information. "
        "Input: a search query string. "
        "Returns: formatted search results with titles, URLs, and snippets."
    )
    metadata: ToolMetadata = ToolMetadata(provider="builtin")

    # ------------------------------------------------------------------
    # LangChain BaseTool 要求实现的方法
    # ------------------------------------------------------------------

    async def _arun(self, query: str) -> str:
        """异步执行搜索。"""
        results = await self._search(query)
        return "\n".join(r["snippet"] for r in results)

    def _run(self, query: str) -> str:
        """同步执行搜索（回退路径）。"""
        results = self._search_sync(query)
        return "\n".join(r["snippet"] for r in results)

    # ------------------------------------------------------------------
    # 搜索实现（当前为占位）
    # ------------------------------------------------------------------

    async def _search(self, query: str, num_results: int = 5) -> list[dict[str, str]]:
        """异步搜索 —— 占位实现，返回示例结果。"""
        return [
            {
                "title": "example",
                "url": "https://example.com",
                "snippet": f"Result for: {query}",
            }
        ]

    def _search_sync(self, query: str, num_results: int = 5) -> list[dict[str, str]]:
        """同步搜索 —— 占位实现，返回示例结果。"""
        return [
            {
                "title": "example",
                "url": "https://example.com",
                "snippet": f"Result for: {query}",
            }
        ]
