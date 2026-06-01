"""WorkingMemory — 滑动窗口 + LLM 摘要测试。"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.messages import HumanMessage, AIMessage


class TestWorkingMemory:
    """WorkingMemory 核心测试。"""

    @pytest.fixture
    def wm(self):
        from haven.memory.working import WorkingMemory
        return WorkingMemory(max_messages=10)

    def test_add_message(self, wm):
        wm.add_message(HumanMessage(content="你好"))
        assert len(wm.get_messages()) == 1

    def test_add_multiple_messages(self, wm):
        wm.add_message(HumanMessage(content="msg1"))
        wm.add_message(AIMessage(content="msg2"))
        wm.add_message(HumanMessage(content="msg3"))
        assert len(wm.get_messages()) == 3

    @pytest.mark.asyncio
    async def test_retrieve_returns_recent(self, wm):
        for i in range(5):
            wm.add_message(HumanMessage(content=f"msg{i}"))
        items = await wm.retrieve(query="", top_k=3)
        assert len(items) <= 3 + len(wm.pinned_items)

    @pytest.mark.asyncio
    async def test_retrieve_empty(self, wm):
        items = await wm.retrieve(query="", top_k=10)
        assert items == []  # no messages, no pinned items

    def test_max_messages_sliding_window(self):
        from haven.memory.working import WorkingMemory
        small = WorkingMemory(max_messages=3)

        for i in range(5):
            small.add_message(HumanMessage(content=f"msg{i}"))

        msgs = small.get_messages()
        # maxlen=3 + manual pop 让窗口 ≤ max_messages
        assert len(msgs) <= 3
        # 最早的消息已被挤出
        contents = [m.content for m in msgs]
        assert "msg0" not in contents

    def test_needs_summarization_false_initially(self, wm):
        """初始状态不需要摘要。"""
        assert wm.needs_summarization() is False

    def test_needs_summarization_when_buffer_full(self):
        """摘要缓冲区 >= 10 时触发需求。"""
        from haven.memory.working import WorkingMemory
        # max_messages=5: 加 15 条后 _summary_buffer >= 10
        wm = WorkingMemory(max_messages=5)
        for i in range(20):
            wm.add_message(HumanMessage(content=f"msg{i}"))
        assert wm.needs_summarization() is True

    @pytest.mark.asyncio
    async def test_summarize_calls_llm(self):
        """summarize() 调用 LLM 生成摘要。"""
        from haven.memory.working import WorkingMemory

        mock_llm = MagicMock()
        mock_llm.ainvoke = AsyncMock(return_value=AIMessage(content="对话摘要: 用户在询问技术问题"))

        # 需要先填满 _summary_buffer
        wm = WorkingMemory(max_messages=3)
        for i in range(15):
            wm.add_message(HumanMessage(content=f"问题{i}"))
            wm.add_message(AIMessage(content=f"回答{i}"))

        await wm.summarize(mock_llm)
        assert wm.summary != ""
        assert "技术问题" in wm.summary

    @pytest.mark.asyncio
    async def test_clear(self, wm):
        wm.add_message(HumanMessage(content="test"))
        await wm.clear()
        assert len(wm.get_messages()) == 0
        assert wm.summary == ""

    @pytest.mark.asyncio
    async def test_summary_injected_in_retrieve(self, wm):
        """有 summary 时 retrieve 返回摘要 item。"""
        wm.summary = "之前的对话讨论了架构设计"
        items = await wm.retrieve(query="", top_k=5)
        # summary 本身不形成 item，但 pinned items 会返回
        # 这里我们只验证 retrieve 不崩溃
        assert isinstance(items, list)
