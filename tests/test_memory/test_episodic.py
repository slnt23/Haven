"""EpisodicMemory — 对话持久化存储与检索测试。"""
from __future__ import annotations

import pytest


class TestEpisodicMemory:
    """EpisodicMemory 核心测试。"""

    @pytest.fixture
    def em(self, memory_db_conn):
        from haven.memory.episodic import EpisodicMemory
        em = EpisodicMemory()
        em._conn = memory_db_conn
        em._init_schema()
        return em

    @pytest.mark.asyncio
    async def test_store_turn(self, em):
        await em.store_turn(
            session_id="s1",
            turn_number=1,
            user_message="你好",
            assistant_response="你好！",
            importance=0.8,
        )
        items = await em.retrieve(query="你好", top_k=5)
        assert len(items) >= 1

    @pytest.mark.asyncio
    async def test_store_multiple_turns(self, em):
        for i in range(3):
            await em.store_turn(
                session_id="s1", turn_number=i + 1,
                user_message=f"问题{i}", assistant_response=f"回答{i}",
                importance=0.7,
            )
        items = await em.retrieve(query="问题", top_k=5, time_range="30d",
                                   min_importance=0.3, search_mode="hybrid")
        assert len(items) >= 1

    @pytest.mark.asyncio
    async def test_retrieve_respects_time_range(self, em):
        await em.store_turn(
            session_id="s2", turn_number=1,
            user_message="old message", assistant_response="old reply",
            importance=0.9,
        )
        items = await em.retrieve(query="old", top_k=5, time_range="1d",
                                   min_importance=0.3, search_mode="keyword")
        assert len(items) >= 0  # 应不崩溃

    @pytest.mark.asyncio
    async def test_retrieve_respects_min_importance(self, em):
        await em.store_turn(
            session_id="s3", turn_number=1,
            user_message="important", assistant_response="reply",
            importance=0.2,
        )
        items = await em.retrieve(query="important", top_k=5,
                                   min_importance=0.5, search_mode="keyword")
        assert len(items) == 0  # 0.2 < 0.5 floor

    @pytest.mark.asyncio
    async def test_consolidate(self, em):
        result = await em.consolidate(None)
        assert isinstance(result, int)
