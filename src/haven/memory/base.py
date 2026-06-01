"""Memory 系统基础类型。

- BaseMemory: 所有 Memory 存储的抽象接口
- MemoryItem: 统一条目模型
- MemoryContext: 检索结果容器（含 format_for_prompt）
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class MemoryItem:
    """所有 Memory 层的统一条目。"""

    id: str
    content: str
    memory_type: str = ""  # working | episodic | semantic | vector
    created_at: datetime = field(default_factory=datetime.now)
    importance: float = 0.5
    access_count: int = 0
    last_accessed_at: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    embedding: list[float] | None = None


@dataclass
class MemoryContext:
    """MemoryManager.retrieve() 的返回结果。

    各 Memory 层的检索结果集合，供 PromptBuilder 组装 system prompt。
    """

    working: list[MemoryItem] = field(default_factory=list)
    episodic: list[MemoryItem] = field(default_factory=list)
    semantic: list[MemoryItem] = field(default_factory=list)
    vector: list[MemoryItem] = field(default_factory=list)

    def format_for_prompt(self) -> str:
        """格式化为 system prompt 注入片段。

        优先级：semantic > episodic > vector
        Working 不注入 prompt（直接追加到 messages）。
        """
        parts: list[str] = []

        if self.semantic:
            lines = ["\n[长期记忆 — 关于当前用户]"]
            for item in self.semantic:
                lines.append(f"- {item.content}")
            parts.append("\n".join(lines))

        if self.episodic:
            lines = ["\n[相关历史对话]"]
            for item in self.episodic:
                ts = item.created_at.strftime("%Y-%m-%d %H:%M")
                lines.append(f"[{ts}] {item.content}")
            parts.append("\n".join(lines))

        if self.vector:
            lines = ["\n[相关知识库片段]"]
            for item in self.vector:
                lines.append(item.content)
            parts.append("\n".join(lines))

        return "\n".join(parts)

    @property
    def total_tokens_estimate(self) -> int:
        """估算总 token 数（1 token ≈ 3 chars）。"""
        return len(self.format_for_prompt()) // 3


class BaseMemory(ABC):
    """Memory 存储的抽象基类。

    每种 Memory 类型实现此接口。
    """

    name: str = "base"

    @abstractmethod
    async def store(self, items: list[MemoryItem]) -> None:
        """存储一批条目。"""
        ...

    @abstractmethod
    async def retrieve(self, query: str = "", top_k: int = 5, **filters: Any) -> list[MemoryItem]:
        """按 query 检索 top_k 条目。"""
        ...

    @abstractmethod
    async def forget(self, item_id: str) -> None:
        """删除指定条目。"""
        ...

    @abstractmethod
    async def clear(self) -> None:
        """清空此 Memory 的全部数据。"""
        ...

    async def consolidate(self, llm: Any = None) -> int:
        """后台整合。返回整合条目数。"""
        return 0
