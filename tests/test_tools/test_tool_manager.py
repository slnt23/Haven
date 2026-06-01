"""ToolManager — Provider 编排 + 工具检索测试。"""
from __future__ import annotations

import pytest


class TestToolManagerProvider:
    """Provider 管理测试。"""

    def test_add_provider(self, empty_tool_manager):
        """添加 provider 成功。"""
        from haven.tools.providers.base import ToolProvider
        from haven.tools.base import HavenTool

        class MockProvider(ToolProvider):
            async def discover(self):
                return []

            async def health_check(self):
                return True

        tm = empty_tool_manager
        tm.add_provider(MockProvider(name="mock_provider"))
        assert "mock_provider" in tm._providers

    def test_add_duplicate_provider_raises(self, empty_tool_manager):
        """重复添加 provider 抛出 ValueError。"""
        from haven.tools.providers.base import ToolProvider

        class MockProvider(ToolProvider):
            async def discover(self):
                return []

            async def health_check(self):
                return True

        tm = empty_tool_manager
        tm.add_provider(MockProvider(name="dup"))
        with pytest.raises(ValueError):
            tm.add_provider(MockProvider(name="dup"))

    def test_remove_provider(self, empty_tool_manager):
        """移除 provider 清理工具。"""
        from haven.tools.providers.base import ToolProvider

        class MockProvider(ToolProvider):
            async def discover(self):
                return []

            async def health_check(self):
                return True

        tm = empty_tool_manager
        tm.add_provider(MockProvider(name="to_remove"))
        tm.remove_provider("to_remove")
        assert "to_remove" not in tm._providers

    def test_list_providers(self, empty_tool_manager):
        from haven.tools.providers.base import ToolProvider

        class MockProvider(ToolProvider):
            async def discover(self):
                return []

            async def health_check(self):
                return True

        tm = empty_tool_manager
        tm.add_provider(MockProvider(name="p1"))
        tm.add_provider(MockProvider(name="p2"))
        assert len(tm.list_providers()) == 2


class TestToolManagerWithBuiltin:
    """与 BuiltinProvider 集成测试。"""

    @pytest.mark.asyncio
    async def test_list_all_returns_tools(self, populated_tool_manager):
        """list_all 返回所有注册工具。"""
        tools = populated_tool_manager.list_all()
        assert len(tools) == 6  # 6 个内置工具

    @pytest.mark.asyncio
    async def test_list_names(self, populated_tool_manager):
        """list_names 返回工具名列表。"""
        names = populated_tool_manager.list_names()
        assert "code_exec" in names
        assert "file_ops" in names
        assert "web_search" in names

    @pytest.mark.asyncio
    async def test_get_tool(self, populated_tool_manager):
        """按名获取工具。"""
        tool = populated_tool_manager.get_tool("code_exec")
        assert tool is not None
        assert tool.name == "code_exec"

    @pytest.mark.asyncio
    async def test_get_tool_nonexistent(self, populated_tool_manager):
        """不存在的工具返回 None。"""
        tool = populated_tool_manager.get_tool("nonexistent")
        assert tool is None

    @pytest.mark.asyncio
    async def test_filter_tools_by_category(self, populated_tool_manager):
        """按类别过滤。"""
        code_tools = populated_tool_manager.filter_tools(category="code")
        assert len(code_tools) == 1
        assert code_tools[0].name == "code_exec"

        search_tools = populated_tool_manager.filter_tools(category="search")
        assert len(search_tools) == 1
        assert search_tools[0].name == "web_search"

    @pytest.mark.asyncio
    async def test_filter_tools_by_tag(self, populated_tool_manager):
        """按标签过滤。"""
        builtin_tools = populated_tool_manager.filter_tools(tag="builtin")
        assert len(builtin_tools) == 6

    @pytest.mark.asyncio
    async def test_get_tools_by_names(self, populated_tool_manager):
        """按名称列表批量获取。"""
        tools = populated_tool_manager.get_tools_by_names(["code_exec", "file_ops"])
        assert len(tools) == 2
        assert {t.name for t in tools} == {"code_exec", "file_ops"}

    @pytest.mark.asyncio
    async def test_get_tools_by_names_skips_missing(self, populated_tool_manager):
        """不存在的名称静默跳过。"""
        tools = populated_tool_manager.get_tools_by_names(["code_exec", "does_not_exist"])
        assert len(tools) == 1

    @pytest.mark.asyncio
    async def test_get_tools_by_tags(self, populated_tool_manager):
        """按标签 OR 匹配。"""
        tools = populated_tool_manager.get_tools_by_tags(["code_exec", "web_search"])
        assert len(tools) >= 2

    @pytest.mark.asyncio
    async def test_get_tools_by_categories(self, populated_tool_manager):
        """按类别 OR 匹配。"""
        tools = populated_tool_manager.get_tools_by_categories(["code", "search"])
        assert len(tools) == 2

    @pytest.mark.asyncio
    async def test_get_status(self, populated_tool_manager):
        """get_status 返回完整状态。"""
        status = populated_tool_manager.get_status()
        assert "providers" in status
        assert "total_tools" in status
        assert status["total_tools"] == 6

    @pytest.mark.asyncio
    async def test_format_status(self, populated_tool_manager):
        """format_status 返回可读字符串。"""
        formatted = populated_tool_manager.format_status()
        assert isinstance(formatted, str)
        assert len(formatted) > 0
