"""SemanticMemory — 实体-事实知识图存储与检索测试。"""
from __future__ import annotations

import pytest


class TestSemanticMemory:
    """SemanticMemory 核心测试。"""

    @pytest.fixture
    def sm(self, memory_db_conn):
        """SemanticMemory 使用临时 SQLite。"""
        from haven.memory.semantic import SemanticMemory

        sm = SemanticMemory()
        sm._conn = memory_db_conn
        sm._init_schema()
        return sm

    @pytest.mark.asyncio
    async def test_store_and_retrieve(self, sm):
        from haven.memory.base import MemoryItem

        items = [
            MemoryItem(
                id="fact_1",
                content="name: 张三",
                memory_type="semantic",
                importance=0.9,
                metadata={
                    "entity_name": "user_1",
                    "key": "name",
                    "value": "张三",
                    "confidence": 0.9,
                    "source_session": "s1",
                    "source_turn": 1,
                    "tags": ["personal"],
                    "entity_type": "user",
                },
            ),
            MemoryItem(
                id="fact_2",
                content="skill: Python",
                memory_type="semantic",
                importance=0.7,
                metadata={
                    "entity_name": "user_1",
                    "key": "skill",
                    "value": "Python",
                    "confidence": 0.7,
                    "source_session": "s1",
                    "source_turn": 2,
                    "tags": ["skill"],
                    "entity_type": "user",
                },
            ),
        ]
        await sm.store(items)

        results = await sm.retrieve(
            query="name",
            top_k=5,
            entity_name="user_1",
            min_confidence=0.5,
        )
        assert len(results) >= 1

    @pytest.mark.asyncio
    async def test_retrieve_respects_confidence(self, sm):
        from haven.memory.base import MemoryItem

        items = [
            MemoryItem(
                id="fact_low",
                content="key1: value1",
                memory_type="semantic",
                importance=0.2,
                metadata={
                    "entity_name": "user_1",
                    "key": "key1",
                    "value": "value1",
                    "confidence": 0.2,
                    "source_session": "s1",
                    "source_turn": 1,
                    "tags": [],
                    "entity_type": "user",
                },
            ),
        ]
        await sm.store(items)

        results = await sm.retrieve(
            query="key1",
            top_k=5,
            entity_name="user_1",
            min_confidence=0.5,  # > 0.2
        )
        assert len(results) == 0

    @pytest.mark.asyncio
    async def test_retrieve_entity_facts(self, sm):
        from haven.memory.base import MemoryItem

        items = [
            MemoryItem(
                id="fact_a",
                content="name: 李四",
                memory_type="semantic",
                importance=0.8,
                metadata={
                    "entity_name": "user_2",
                    "key": "name",
                    "value": "李四",
                    "confidence": 0.8,
                    "source_session": "s2",
                    "source_turn": 1,
                    "tags": ["personal"],
                    "entity_type": "user",
                },
            ),
        ]
        await sm.store(items)

        facts = await sm.retrieve_entity_facts("user_2")
        assert len(facts) >= 1

    @pytest.mark.asyncio
    async def test_retrieve_empty_entity(self, sm):
        """不存在的实体返回空列表。"""
        facts = await sm.retrieve_entity_facts("nonexistent_user")
        assert facts == []

    @pytest.mark.asyncio
    async def test_consolidate(self, sm):
        """consolidate 返回整数计数值。"""
        result = await sm.consolidate(None)
        assert isinstance(result, int)
