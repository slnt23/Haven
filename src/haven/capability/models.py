"""Capability 统一接口 —— Tool 与 Skill 共享的抽象基类。

Capability: 一切能力的基类，定义 name / description / metadata / enabled。
Tool: 可调用能力，包装 LangChain BaseTool。
Skill: 提示词注入能力，通过 activate() 返回 prompt 文本。

优先使用 LangChain 官方 Tool 体系。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from langchain_core.tools import BaseTool as LangChainBaseTool


# ============================================================================
# CapabilityMetadata
# ============================================================================


@dataclass
class CapabilityMetadata:
    """能力的静态描述信息。"""

    name: str
    description: str = ""
    version: str = "1.0"
    enabled: bool = True
    provider: str = "builtin"  # builtin / mcp / user
    tags: list[str] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)


# ============================================================================
# Capability (ABC)
# ============================================================================


class Capability(ABC):
    """一切能力的抽象基类。

    Tool 和 Skill 均继承自此接口，统一注册到 CapabilityRegistry。
    """

    @property
    @abstractmethod
    def metadata(self) -> CapabilityMetadata:
        """能力的静态元数据。"""
        ...

    @property
    def name(self) -> str:
        return self.metadata.name

    @property
    def description(self) -> str:
        return self.metadata.description

    @property
    def enabled(self) -> bool:
        return self.metadata.enabled

    @abstractmethod
    async def validate(self) -> bool:
        """检查能力是否可用（连接正常、文件存在等）。"""
        ...


# ============================================================================
# Tool
# ============================================================================


class Tool(Capability):
    """可调用能力 —— 包装 LangChain BaseTool。

    每个 Tool 持有底层 LangChain BaseTool，对外提供统一的 Capability 接口。
    Agent 通过 ToolRegistry 获取 langchain_tool 列表绑定到 LLM。
    """

    def __init__(
        self,
        base_tool: LangChainBaseTool,
        *,
        provider: str = "builtin",
        version: str = "1.0",
        requires_confirmation: bool = False,
        timeout_seconds: int = 300,
    ) -> None:
        self._tool = base_tool
        self._metadata = CapabilityMetadata(
            name=base_tool.name,
            description=base_tool.description or "",
            version=version,
            provider=provider,
            extra={
                "requires_confirmation": requires_confirmation,
                "timeout_seconds": timeout_seconds,
            },
        )

    @property
    def metadata(self) -> CapabilityMetadata:
        return self._metadata

    @property
    def langchain_tool(self) -> LangChainBaseTool:
        """获取底层 LangChain 工具，供 Agent 绑定使用。"""
        return self._tool

    async def execute(self, **kwargs: Any) -> Any:
        """异步执行工具。

        委托给 LangChain BaseTool.ainvoke()。
        """
        return await self._tool.ainvoke(kwargs)

    async def validate(self) -> bool:
        """工具总是可用的（Provider 层已做健康检查）。"""
        return True

    def __repr__(self) -> str:
        return f"<Tool name={self.name!r} provider={self.metadata.provider!r}>"


# ============================================================================
# Skill
# ============================================================================


@dataclass
class Skill(Capability):
    """提示词注入能力 —— 从 .md 文件加载，LLM 按语义匹配激活。

    Skill 不包含可执行代码，仅包含结构化元数据 + Markdown prompt 文本。
    """

    name: str = ""
    description: str = ""
    prompt: str = ""
    tags: list[str] = field(default_factory=list)
    tools: list[str] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)
    version: str = "1.0"
    default: bool = False
    category: str = ""
    source_file: Path = field(default_factory=Path)

    _enabled: bool = True

    @property
    def metadata(self) -> CapabilityMetadata:
        return CapabilityMetadata(
            name=self.name,
            description=self.description,
            version=self.version,
            enabled=self._enabled,
            provider="user",
            tags=self.tags,
            extra={
                "tools": self.tools,
                "dependencies": self.dependencies,
                "default": self.default,
                "category": self.category,
            },
        )

    @property
    def enabled(self) -> bool:
        return self._enabled

    def activate(self) -> str:
        """激活此 Skill —— 返回要注入 LLM system_prompt 的文本。"""
        return self.prompt

    async def validate(self) -> bool:
        """Skill 有 prompt 内容即有效。"""
        return bool(self.prompt)

    @property
    def tool_set(self) -> set[str]:
        return set(self.tools)

    def requires_tool(self, tool_name: str) -> bool:
        return tool_name in self.tools

    def __repr__(self) -> str:
        return (
            f"<Skill name={self.name!r}"
            f" tags={self.tags} tools={self.tools}"
            f" deps={self.dependencies} default={self.default}>"
        )
