"""ToolProvider 抽象基类 + ProviderInfo + ProviderStatus 测试。"""
from __future__ import annotations

import pytest


class TestProviderStatus:
    """ProviderStatus 枚举测试。"""

    def test_status_values(self):
        from haven.tools.providers.base import ProviderStatus
        values = [s.value for s in ProviderStatus]
        assert "uninitialized" in values
        assert "connecting" in values
        assert "connected" in values
        assert "degraded" in values
        assert "disconnected" in values
        assert "error" in values


class TestProviderInfo:
    """ProviderInfo 数据类测试。"""

    def test_defaults(self):
        from haven.tools.providers.base import ProviderInfo
        info = ProviderInfo(name="test")
        assert info.name == "test"
        assert info.type == "custom"
        assert info.tool_count == 0
        assert info.status.value == "uninitialized"


class TestToolProvider:
    """ToolProvider 生命周期测试。"""

    @pytest.fixture
    def provider(self):
        from haven.tools.providers.base import ToolProvider
        from haven.tools.base import HavenTool

        class TestProvider(ToolProvider):
            async def discover(self):
                return []

            async def health_check(self):
                return True

        return TestProvider(name="test_provider", provider_type="test")

    def test_initial_state(self, provider):
        assert provider.info.name == "test_provider"
        assert provider.info.status.value == "uninitialized"
        assert provider.list_tools() == []

    @pytest.mark.asyncio
    async def test_start_stop_cycle(self, provider):
        await provider.start()
        assert provider.info.status.value == "connected"

        await provider.stop()
        assert provider.info.status.value == "disconnected"

    @pytest.mark.asyncio
    async def test_refresh(self, provider):
        await provider.start()
        await provider.refresh()
        assert provider.info.tool_count == 0  # discover 返回空列表

    def test_get_tool_nonexistent(self, provider):
        assert provider.get_tool("nope") is None

    def test_filter_tools(self, provider):
        result = provider.filter_tools(category="code")
        assert result == []
