"""WorkingMemory — 滑动窗口 + 摘要压缩。

不持久化。进程生命周期。
超出窗口的消息自动进入摘要缓冲区，由 LLM 按需压缩。
"""

from __future__ import annotations

from collections import deque
from typing import Any

from langchain_core.messages import BaseMessage

from haven.memory.base import BaseMemory, MemoryItem


class WorkingMemory(BaseMemory):
    """当前会话上下文。纯内存，不持久化。

    - sliding_window: deque[BaseMessage] — 最近 N 条消息
    - pinned_items:    list[MemoryItem]  — 重要信息（始终保留）
    - summary:         str               — 超出窗口的消息摘要
    """

    name = "working"

    def __init__(self, max_messages: int = 100):
        self.max_messages = max_messages
        self.sliding_window: deque[BaseMessage] = deque(maxlen=max_messages)
        self.pinned_items: list[MemoryItem] = []
        self.summary: str = ""
        self._summary_buffer: list[BaseMessage] = []

    # ========== BaseMemory ==========

    async def store(self, items: list[MemoryItem]) -> None:
        pass  # 使用 add_message()

    async def retrieve(self, query: str = "", top_k: int = 20, **filters: Any) -> list[MemoryItem]:
        items: list[MemoryItem] = list(self.pinned_items)
        for msg in list(self.sliding_window)[-top_k:]:
            items.append(
                MemoryItem(
                    id=f"wm_{id(msg)}",
                    content=msg.content if hasattr(msg, "content") else str(msg),
                    memory_type="working",
                    importance=0.8,
                )
            )
        return items

    async def forget(self, item_id: str) -> None:
        self.pinned_items = [i for i in self.pinned_items if i.id != item_id]

    async def clear(self) -> None:
        self.sliding_window.clear()
        self.pinned_items.clear()
        self.summary = ""
        self._summary_buffer.clear()

    # ========== 专用 API ==========

    def add_message(self, message: BaseMessage) -> None:
        self.sliding_window.append(message)
        if len(self.sliding_window) >= self.max_messages:
            overflow = self.sliding_window.popleft()
            self._summary_buffer.append(overflow)

    def add_messages(self, messages: list[BaseMessage]) -> None:
        for msg in messages:
            self.add_message(msg)

    def pin(self, item: MemoryItem) -> None:
        self.pinned_items.append(item)

    def get_messages(self) -> list[BaseMessage]:
        return list(self.sliding_window)

    def needs_summarization(self) -> bool:
        return len(self._summary_buffer) >= 10

    async def summarize(self, llm: Any) -> str:
        if not self._summary_buffer:
            return self.summary

        buffer_content = "\n".join(
            m.content if hasattr(m, "content") else str(m) for m in self._summary_buffer
        )

        prompt = (
            f"总结以下历史对话的要点，保留关键信息。用中文，不超过 200 字:\n\n"
            f"{self.summary + chr(10) if self.summary else ''}"
            f"{buffer_content}\n\n要点:"
        )

        try:
            from langchain_core.messages import HumanMessage

            response = await llm.ainvoke([HumanMessage(content=prompt)])
            self.summary = (
                response.content if hasattr(response, "content") else str(response)
            ).strip()
        except Exception:
            pass

        self._summary_buffer.clear()
        return self.summary
