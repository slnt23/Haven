"""WorkingMemory — 滑动窗口 + 摘要压缩。

短期记忆，不持久化，进程生命周期。
超出窗口的消息自动进入摘要缓冲区，由 LLM 按需压缩。
消息直接作为 LangChain BaseMessage 追加到 Agent 的消息列表中。
"""

from __future__ import annotations

from collections import deque
from typing import Any

from langchain_core.messages import BaseMessage

from haven.memory.base import BaseMemory, MemoryItem


class WorkingMemory(BaseMemory):
    """当前会话上下文。纯内存，不持久化。

    属性:
        sliding_window:   最近 N 条消息的固定大小窗口
        pinned_items:     用户置顶的重要信息（始终保留，不被挤出）
        summary:          超出窗口的消息的 LLM 摘要
        _summary_buffer:  被挤出窗口的消息暂存区，攒够后触发摘要
    """

    name = "working"

    def __init__(self, max_messages: int = 100):
        self.max_messages = max_messages
        # deque 设 maxlen 后，append 时自动挤出最旧消息
        self.sliding_window: deque[BaseMessage] = deque(maxlen=max_messages)
        self.pinned_items: list[MemoryItem] = []
        self.summary: str = ""
        self._summary_buffer: list[BaseMessage] = []

    # ========== BaseMemory 接口 ==========

    async def store(self, items: list[MemoryItem]) -> None:
        pass  # 使用 add_message() 代替

    async def retrieve(
        self, query: str = "", top_k: int = 20, **filters: Any
    ) -> list[MemoryItem]:
        """返回最近的消息 + 置顶项。

        Working 层不按 query 检索，始终返回最近的消息。
        """
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
        """追加一条消息到滑动窗口。

        当窗口满了，最旧的消息会被自动挤出到摘要缓冲区。
        """
        self.sliding_window.append(message)
        # deque 设了 maxlen，但 append 不会自动 pop——
        # 需要手动检查是否超出限制
        if len(self.sliding_window) >= self.max_messages:
            overflow = self.sliding_window.popleft()
            self._summary_buffer.append(overflow)

    def add_messages(self, messages: list[BaseMessage]) -> None:
        """批量追加消息。"""
        for msg in messages:
            self.add_message(msg)

    def pin(self, item: MemoryItem) -> None:
        """置顶一条重要信息，检索时始终返回。"""
        self.pinned_items.append(item)

    def get_messages(self) -> list[BaseMessage]:
        """获取当前滑动窗口中的所有消息。"""
        return list(self.sliding_window)

    def needs_summarization(self) -> bool:
        """摘要缓冲区是否达到触发阈值（10 条）。"""
        return len(self._summary_buffer) >= 10

    async def summarize(self, llm: Any) -> str:
        """将摘要缓冲区中的消息压缩为一段中文摘要。

        调用辅助 LLM，保留关键信息，不超过 200 字。
        新旧摘要会拼接在一起传给 LLM，保证信息的连续性。
        """
        if not self._summary_buffer:
            return self.summary

        # 拼接缓冲区内消息的文本
        buffer_content = "\n".join(
            m.content if hasattr(m, "content") else str(m)
            for m in self._summary_buffer
        )

        # 带上旧摘要，确保信息不丢失
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
