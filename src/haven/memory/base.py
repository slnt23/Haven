"""Memory 系统基础类型。

- BaseMemory: 所有 Memory 存储的抽象接口
- MemoryItem: 统一条目模型，所有层共用
- MemoryContext: 检索结果容器（含 format_for_prompt 格式化）
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class MemoryItem:
    """所有 Memory 层的统一条目。

    content 字段含义因 memory_type 而异：
    - working:   人类消息/AI消息文本
    - episodic:  "用户: ...\\nAI: ..." 格式的对话摘要
    - semantic:  自然语言事实陈述，如"用户叫张三，住在北京"
    - vector:    嵌入用的原始对话文本
    """

    id: str  # 唯一标识，格式：{层}_{会话}_{轮次}_{随机}
    content: str  # 展示文本，格式因 memory_type 而异
    memory_type: str = ""  # working | episodic | semantic | vector
    created_at: datetime = field(default_factory=datetime.now)
    importance: float = 0.5  # 0.0-1.0，1.0 为最重要
    access_count: int = 0  # 被检索命中的次数
    last_accessed_at: datetime | None = None  # 最近一次被检索的时间
    metadata: dict[str, Any] = field(default_factory=dict)  # 各层自定义元数据
    embedding: list[float] | None = None  # 向量嵌入，仅 VectorMemory 使用


@dataclass
class MemoryContext:
    """MemoryManager.retrieve() 的返回结果。

    四层检索结果集合，由 MemoryMiddleware 注入 system prompt。
    format_for_prompt() 按 语义 > 情节 > 向量 优先级组装，
    Working 不注入 prompt（直接追加到 messages 中）。
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

        # 语义记忆 — 自然语言事实，优先级最高
        if self.semantic:
            lines = ["\n[对你的了解 — 长期记忆]"]
            for item in self.semantic:
                # item.content 是自然语言句子，直接展示
                lines.append(f"- {item.content}")
            parts.append("\n".join(lines))

        # 情节记忆 — 带时间戳的历史对话
        if self.episodic:
            lines = ["\n[相关历史对话]"]
            for item in self.episodic:
                ts = item.created_at.strftime("%Y-%m-%d %H:%M")
                lines.append(f"[{ts}] {item.content}")
            parts.append("\n".join(lines))

        # 向量记忆 — 语义相似片段
        if self.vector:
            lines = ["\n[相关知识库片段]"]
            for item in self.vector:
                lines.append(item.content)
            parts.append("\n".join(lines))

        return "\n".join(parts)

    @property
    def total_tokens_estimate(self) -> int:
        """估算总 token 数（1 token ≈ 3 字符，粗略估算）。"""
        return len(self.format_for_prompt()) // 3


class BaseMemory(ABC):
    """Memory 存储的抽象基类。

    每种 Memory 层（Working / Episodic / Semantic / Vector）
    必须实现 store / retrieve / forget / clear 四个方法。
    consolidate 为可选，用于后台维护。
    """

    name: str = "base"

    @abstractmethod
    async def store(self, items: list[MemoryItem]) -> None:
        """存储一批 MemoryItem。"""

    @abstractmethod
    async def retrieve(
            self, query: str = "", top_k: int = 5, **filters: Any
    ) -> list[MemoryItem]:
        """按 query 检索 top_k 条最相关的条目。

        filters 为各层自定义过滤条件（如 entity_name、session_id 等）。
        """

    @abstractmethod
    async def forget(self, item_id: str) -> None:
        """删除指定条目。"""

    @abstractmethod
    async def clear(self) -> None:
        """清空此层全部数据。"""

    async def consolidate(self, llm: Any = None) -> int:
        """后台整合。返回整合的条目数。默认空操作。"""
        return 0
