"""HavenTool — 统一工具基类。

继承 LangChain BaseTool，增加:
  - ToolMetadata: 声明式元数据（provider, category, permissions, rate_limit）
  - health_check(): 可用性检查
  - 零摩擦接入 AgentRuntime
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from langchain_core.tools import BaseTool as LCBaseTool
from pydantic import BaseModel, Field


class ToolCategory(str, Enum):
    CODE = "code"
    FILE = "file"
    SEARCH = "search"
    KNOWLEDGE = "knowledge"
    COMMUNICATION = "communication"
    SYSTEM = "system"
    CUSTOM = "custom"


class ToolPermission(str, Enum):
    READ = "read"
    WRITE = "write"
    EXECUTE = "execute"
    SEND = "send"


class ToolMetadata(BaseModel):
    """工具的声明式元数据。供 ToolManager 做过滤/ACL/审计。"""

    provider: str = ""
    category: ToolCategory = ToolCategory.CUSTOM
    permissions: list[ToolPermission] = Field(default_factory=list)
    requires_confirmation: bool = False
    rate_limit_per_minute: int = 0
    cost_estimate: str = ""                     # low / medium / high
    timeout_seconds: int = 30
    tags: list[str] = Field(default_factory=list)
    version: str = "1.0"


class HavenTool(LCBaseTool):
    """Haven 统一工具基类。

    所有工具（内置 / MCP / OpenAPI / 自定义）继承或适配到此类型。
    兼容 LangChain BaseTool，可直接用于 ``llm.bind_tools()``。

    子类只需实现:
      - name: str
      - description: str
      - _run(*args, **kwargs) → Any
      - 可选 _arun(*args, **kwargs) → Any
    """

    metadata: ToolMetadata = Field(default_factory=ToolMetadata)

    # 覆盖 LangChain 默认值
    name: str = ""
    description: str = ""
    return_direct: bool = False

    async def health_check(self) -> bool:
        """检查工具是否可用。内置工具始终返回 True。"""
        return True

    def __repr__(self) -> str:
        provider = self.metadata.provider or "unknown"
        return (
            f"<HavenTool name={self.name!r} provider={provider!r}"
            f" category={self.metadata.category.value}>"
        )
