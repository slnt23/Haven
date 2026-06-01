"""MemoryManager — 四层记忆统一编排测试。"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import HumanMessage, AIMessage


class TestMemoryManagerRecordTurn:
    """MemoryManager.record_turn() — 核心存储流程。"""

    @pytest.fixture
    def mm(self, temp_db):
        """MemoryManager 使用临时 SQLite。"""
        from haven.memory.manager import MemoryManager

        with patch("haven.memory.working.WorkingMemory"), \
             patch("haven.memory.episodic.EpisodicMemory") as mock_ep, \
             patch("haven.memory.semantic.SemanticMemory") as mock_sem, \
             patch("haven.memory.vector.VectorMemory") as mock_vec:

            mm = MemoryManager(
                session_id="test_session",
                entity_name="test_user",
                channel="cli",
                enable_vector=False,
            )

            # 设置 mock
            mm.working = MagicMock()
            mm.working.add_message = MagicMock()
            mm.working.needs_summarization = MagicMock(return_value=False)

            mm.episodic = MagicMock()
            mm.episodic.store_turn = AsyncMock()

            mm.semantic = MagicMock()
            mm.semantic.store = AsyncMock()

            mm.vector = None

            yield mm

    @pytest.mark.asyncio
    async def test_record_turn_adds_to_working(self, mm):
        """record_turn 立即追加到 WorkingMemory。"""
        await mm.record_turn("你好", "你好！", persist=False)
        assert mm.working.add_message.call_count >= 2

    @pytest.mark.asyncio
    async def test_record_turn_persists_to_episodic(self, mm):
        """persist=True 时持久化到 Episodic。"""
        await mm.record_turn("你好", "你好！", persist=True)
        mm.episodic.store_turn.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_record_turn_skip_persist(self, mm):
        """persist=False 时跳过 Episodic 持久化。"""
        await mm.record_turn("你好", "你好！", persist=False)
        mm.episodic.store_turn.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_record_turn_increments_counter(self, mm):
        """每轮对话 counter +1。"""
        assert mm.turn_count == 0
        await mm.record_turn("msg1", "reply1", persist=False)
        assert mm.turn_count == 1
        await mm.record_turn("msg2", "reply2", persist=False)
        assert mm.turn_count == 2


class TestMemoryManagerRetrieve:
    """MemoryManager.retrieve() — 多路并行检索。"""

    @pytest.fixture
    def mm(self, temp_db):
        from haven.memory.manager import MemoryManager
        from haven.memory.base import MemoryItem

        with patch("haven.memory.working.WorkingMemory"), \
             patch("haven.memory.episodic.EpisodicMemory"), \
             patch("haven.memory.semantic.SemanticMemory"), \
             patch("haven.memory.vector.VectorMemory"):

            mm = MemoryManager(
                session_id="test_session",
                entity_name="test_user",
                channel="cli",
                enable_vector=False,
            )

            # Working 返回最近消息
            mm.working = MagicMock()
            mm.working.retrieve = AsyncMock(return_value=[
                MemoryItem(id="1", content="最近的消息", memory_type="working")
            ])

            # Episodic 返回历史记录
            mm.episodic = MagicMock()
            mm.episodic.retrieve = AsyncMock(return_value=[
                MemoryItem(id="2", content="历史对话", memory_type="episodic")
            ])

            # Semantic 返回事实
            mm.semantic = MagicMock()
            mm.semantic.retrieve = AsyncMock(return_value=[
                MemoryItem(id="3", content="用户偏好", memory_type="semantic")
            ])

            mm.vector = None

            yield mm

    @pytest.mark.asyncio
    async def test_retrieve_parallel(self, mm):
        """retrieve 并行查询所有层。"""
        ctx = await mm.retrieve(task="帮我写代码")

        assert len(ctx.working) >= 1
        assert len(ctx.episodic) >= 1
        assert len(ctx.semantic) >= 1

    @pytest.mark.asyncio
    async def test_retrieve_without_task(self, mm):
        """无 task 时也能检索。"""
        ctx = await mm.retrieve(task="")
        assert ctx is not None
        assert len(ctx.working) >= 1


class TestMemoryManagerEntity:
    """MemoryManager 实体管理测试。"""

    @pytest.fixture
    def mm(self, temp_db):
        from haven.memory.manager import MemoryManager

        with patch("haven.memory.working.WorkingMemory"), \
             patch("haven.memory.episodic.EpisodicMemory"), \
             patch("haven.memory.semantic.SemanticMemory"), \
             patch("haven.memory.vector.VectorMemory"):

            mm = MemoryManager(
                session_id="test_session",
                entity_name="test_user",
                channel="cli",
                enable_vector=False,
            )
            mm.working = MagicMock()
            mm.episodic = MagicMock()
            mm.semantic = MagicMock()
            mm.vector = None
            yield mm

    @pytest.mark.asyncio
    async def test_get_entity_profile(self, mm):
        from haven.memory.base import MemoryItem

        mm.semantic.retrieve_entity_facts = AsyncMock(return_value=[
            MemoryItem(id="f1", content="name: 张三", memory_type="semantic"),
        ])
        facts = await mm.get_entity_profile("test_user")
        assert len(facts) >= 1
        mm.semantic.retrieve_entity_facts.assert_awaited_once_with("test_user")

    @pytest.mark.asyncio
    async def test_get_entity_profile_default(self, mm):
        """不传 entity_name 时使用 self.entity_name。"""
        from haven.memory.base import MemoryItem

        mm.semantic.retrieve_entity_facts = AsyncMock(return_value=[])
        await mm.get_entity_profile()
        mm.semantic.retrieve_entity_facts.assert_awaited_once_with("test_user")


class TestMemoryManagerEstimateImportance:
    """重要性估算算法测试。"""

    def test_estimate_with_keywords(self):
        from haven.memory.manager import MemoryManager

        score = MemoryManager._estimate_importance("我叫张三", "你好")
        assert score >= 0.3
        # "我叫" 命中 1 次关键词
        assert score == pytest.approx(0.45, abs=0.1)

    def test_estimate_no_keywords(self):
        from haven.memory.manager import MemoryManager

        score = MemoryManager._estimate_importance("今天天气不错", "是的")
        assert score == pytest.approx(0.3, abs=0.05)

    def test_estimate_max_capped(self):
        from haven.memory.manager import MemoryManager

        # 大量关键词 → 上限 0.9
        score = MemoryManager._estimate_importance(
            "我叫张三，我喜欢吃辣，我住在北京，我的电话是123，紧急",
            "好的记住了"
        )
        assert score <= 0.9
