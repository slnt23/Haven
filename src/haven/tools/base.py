"""工具基类 —— 统一的 HavenTool，继承 LangChain BaseTool。

所有工具（内置 / MCP / 自定义）最终都是 BaseTool 子类。
不设分类、不设权限 —— LLM 通过 Function Calling 自行决定调用哪个工具。
"""

from __future__ import annotations

from langchain_core.tools import BaseTool as LCBaseTool
from pydantic import Field

from haven.tools.metadata import ToolMetadata


class HavenTool(LCBaseTool):
    """Haven 工具基类，兼容 LangChain BaseTool。

    可直接传入 ``create_react_agent(model=..., tools=[...])``。

    子类需实现：
      - name: str           — 工具名称（LLM 据此选择）
      - description: str    — 工具描述（LLM 据此判断用途）
      - _run(*args, **kwargs) → Any     — 同步执行
      - _arun(*args, **kwargs) → Any    — 异步执行（可选）
    """

    # 轻量级元数据：来源 provider、版本等
    metadata: ToolMetadata = Field(default_factory=ToolMetadata)

    # LangChain BaseTool 要求的字段
    name: str = ""
    description: str = ""
    return_direct: bool = False

    async def health_check(self) -> bool:
        """健康检查。内置工具始终返回 True，MCP 工具检查连接状态。"""
        return True

    def __repr__(self) -> str:
        provider = self.metadata.provider or "unknown"
        return f"<HavenTool name={self.name!r} provider={provider!r}>"
