"""AgentMemory — V1 兼容 facade 测试。"""
from __future__ import annotations

import pytest
from langchain_core.messages import HumanMessage, AIMessage


class TestAgentMemoryMessages:
    """消息队列测试。"""

    @pytest.fixture
    def am(self):
        from haven.core.memory import AgentMemory
        return AgentMemory(max_messages=10)

    def test_add_message(self, am):
        am.add_message(HumanMessage(content="hello"))
        assert len(am) == 1
        assert am.get_history()[0].content == "hello"

    def test_add_messages_batch(self, am):
        am.add_messages([
            HumanMessage(content="a"),
            AIMessage(content="b"),
            HumanMessage(content="c"),
        ])
        assert len(am) == 3

    def test_get_history_returns_copy(self, am):
        am.add_message(HumanMessage(content="orig"))
        history = am.get_history()
        history[0] = HumanMessage(content="modified")
        # 内部 deque 未被修改
        assert am.get_history()[0].content == "orig"

    def test_clear(self, am):
        am.add_message(HumanMessage(content="test"))
        am.add_message(AIMessage(content="reply"))
        assert len(am) == 2
        am.clear()
        assert len(am) == 0

    def test_max_messages_enforced(self):
        from haven.core.memory import AgentMemory
        small = AgentMemory(max_messages=3)
        for i in range(5):
            small.add_message(HumanMessage(content=f"msg{i}"))
        assert len(small) == 3


class TestAgentMemorySession:
    """会话标识测试。"""

    @pytest.fixture
    def am(self):
        from haven.core.memory import AgentMemory
        return AgentMemory()

    def test_default_session_id(self, am):
        assert am.session_id == "default"

    def test_set_session_id(self, am):
        am.session_id = "custom_session"
        assert am.session_id == "custom_session"

    def test_entity_name_defaults_to_session(self, am):
        assert am.entity_name == "default"

    def test_set_entity_name(self, am):
        am.entity_name = "张三"
        assert am.entity_name == "张三"

    def test_channel_property(self, am):
        assert am.channel == "cli"
        am.channel = "socket"
        assert am.channel == "socket"


class TestAgentMemoryMetadata:
    """Metadata 字典测试。"""

    def test_metadata_storage(self):
        from haven.core.memory import AgentMemory
        am = AgentMemory()
        am.metadata["key"] = "value"
        assert am.metadata["key"] == "value"

    def test_clear_also_clears_metadata(self):
        from haven.core.memory import AgentMemory
        am = AgentMemory()
        am.metadata["key"] = "value"
        am.clear()
        assert len(am.metadata) == 0


class TestAgentMemoryManager:
    """MemoryManager facade 测试。"""

    @pytest.fixture
    def am(self):
        from haven.core.memory import AgentMemory
        am = AgentMemory()
        am.session_id = "test_session"
        am.entity_name = "test_user"
        return am

    def test_manager_lazy_init(self, am):
        """首次访问 manager 时懒初始化。"""
        mgr = am.manager
        assert mgr is not None
        assert mgr.session_id == "test_session"
        assert mgr.entity_name == "test_user"

    def test_manager_cached(self, am):
        """重复访问返回同一实例。"""
        mgr1 = am.manager
        mgr2 = am.manager
        assert mgr1 is mgr2

    def test_session_propagates_to_manager(self, am):
        """session_id 变更时同步到已初始化的 manager。"""
        mgr = am.manager
        am.session_id = "new_session"
        assert mgr.session_id == "new_session"
