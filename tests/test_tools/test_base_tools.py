"""HavenTool / ToolMetadata / ToolCategory 基础类型测试。"""
from __future__ import annotations

import pytest


class TestToolMetadata:
    """ToolMetadata 测试。"""

    def test_default_metadata(self):
        from haven.tools.base import ToolMetadata
        meta = ToolMetadata()
        assert meta.provider == ""
        assert meta.category.value == "custom"
        assert meta.permissions == []
        assert meta.requires_confirmation is False
        assert meta.rate_limit_per_minute == 0
        assert meta.timeout_seconds == 30

    def test_metadata_with_values(self):
        from haven.tools.base import ToolMetadata, ToolCategory, ToolPermission
        meta = ToolMetadata(
            provider="test",
            category=ToolCategory.CODE,
            permissions=[ToolPermission.READ, ToolPermission.EXECUTE],
            tags=["test", "code"],
        )
        assert meta.provider == "test"
        assert meta.category == ToolCategory.CODE
        assert ToolPermission.READ in meta.permissions
        assert "test" in meta.tags


class TestToolCategory:
    """ToolCategory 枚举测试。"""

    def test_all_categories(self):
        from haven.tools.base import ToolCategory
        values = [c.value for c in ToolCategory]
        assert "code" in values
        assert "file" in values
        assert "search" in values
        assert "knowledge" in values
        assert "communication" in values
        assert "system" in values
        assert "custom" in values


class TestToolPermission:
    """ToolPermission 枚举测试。"""

    def test_all_permissions(self):
        from haven.tools.base import ToolPermission
        values = [p.value for p in ToolPermission]
        assert "read" in values
        assert "write" in values
        assert "execute" in values
        assert "send" in values


class TestHavenTool:
    """HavenTool 表示测试。"""

    def test_repr(self):
        from haven.tools.base import HavenTool, ToolMetadata, ToolCategory

        meta = ToolMetadata(provider="builtin", category=ToolCategory.CODE)

        class MyTool(HavenTool):
            name: str = "my_tool"
            description: str = "测试工具"
            metadata: ToolMetadata = meta

            def _run(self, **kwargs):
                return "ok"

        tool = MyTool()
        r = repr(tool)
        assert "my_tool" in r
        assert "builtin" in r

    def test_health_check(self):
        from haven.tools.base import HavenTool

        class T(HavenTool):
            name: str = "t"
            description: str = "d"

            def _run(self, **kwargs):
                return "ok"

        import asyncio
        result = asyncio.run(T().health_check())
        assert result is True
