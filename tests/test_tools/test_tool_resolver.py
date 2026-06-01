"""ToolResolver — 5 级动态工具解析测试。"""
from __future__ import annotations

import pytest


class TestToolResolverResolve:
    """ToolResolver.resolve() 核心测试。"""

    def test_resolve_by_exact_name(self, tool_resolver, register_test_skills):
        """Level 1: 精确名称匹配成功。"""
        result = tool_resolver.resolve(["coder"], channel="cli")
        assert len(result.tools) == 3  # code_exec + file_ops + web_search
        tool_names = [t.name for t in result.tools]
        assert "code_exec" in tool_names
        assert "file_ops" in tool_names
        assert "web_search" in tool_names

    def test_resolve_multiple_skills_dedup(self, tool_resolver, register_test_skills):
        """多 skill 同名工具去重。"""
        # coder 和 code_review 都声明了 code_exec
        result = tool_resolver.resolve(["coder", "code_review"], channel="cli")
        code_exec_count = sum(1 for t in result.tools if t.name == "code_exec")
        assert code_exec_count == 1  # 去重

    def test_resolve_medical_skill(self, tool_resolver, register_test_skills):
        """medical skill → medical_kb 工具。"""
        result = tool_resolver.resolve(["medical"], channel="cli")
        tool_names = [t.name for t in result.tools]
        assert "medical_kb" in tool_names

    def test_resolve_empty_skills(self, tool_resolver):
        """空 skill 列表 → 空工具列表。"""
        result = tool_resolver.resolve([], channel="cli")
        assert len(result.tools) == 0

    def test_resolve_unknown_skill(self, tool_resolver):
        """未知 skill → 空工具 + unresolved。"""
        result = tool_resolver.resolve(["nonexistent_skill"], channel="cli")
        assert len(result.tools) == 0

    def test_resolve_cache(self, tool_resolver, register_test_skills):
        """相同 skill 组合命中缓存。"""
        result1 = tool_resolver.resolve(["coder"], channel="cli")
        result2 = tool_resolver.resolve(["coder"], channel="cli")
        assert result1.tool_names == result2.tool_names

    def test_resolve_different_channel_different_cache(self, tool_resolver, register_test_skills):
        """不同 channel 不同缓存 key。"""
        r1 = tool_resolver.resolve(["coder"], channel="cli")
        r2 = tool_resolver.resolve(["coder"], channel="socket")
        # 缓存 key 包含 channel
        assert r1.tool_names == r2.tool_names  # 工具相同但缓存 key 不同

    def test_resolve_by_tag(self, tool_resolver):
        """Level 3: 标签匹配 — 当名称不匹配时走标签。"""
        # 直接传入工具标签（不通过 skill）
        # ToolResolver 需要 skill 名来收集 requirements，所以这里测试纯标签情况
        # 工具以 'builtin' 标签注册
        tools = tool_resolver._tm.get_tools_by_tags(["builtin"])
        assert len(tools) == 6

    def test_resolve_by_category(self, tool_resolver):
        """Level 4: 类别匹配。"""
        tools = tool_resolver._tm.get_tools_by_categories(["code"])
        assert len(tools) == 1
        assert tools[0].name == "code_exec"


class TestResolveResult:
    """ResolveResult 属性测试。"""

    def test_all_resolved_true(self, tool_resolver, register_test_skills):
        result = tool_resolver.resolve(["coder"], channel="cli")
        assert result.all_resolved is True

    def test_all_resolved_false(self, tool_resolver, register_test_skills):
        """有 unresolved 时 all_resolved=False。"""
        # skill 声明了不存在的工具 — 需要先注册一个 skill 含无效工具
        from haven.skills.base_skill import BaseSkill
        from haven.skills.registry import SkillRegistry

        broken = BaseSkill(
            name="broken",
            description="broken skill",
            tools=["nonexistent_tool"],
            default=False,
        )
        SkillRegistry.register_instance(broken)

        result = tool_resolver.resolve(["broken"], channel="cli")
        assert result.all_resolved is False
        assert len(result.unresolved) > 0

    def test_warnings_for_unresolved(self, tool_resolver, register_test_skills):
        """未解析的工具产生警告。"""
        from haven.skills.base_skill import BaseSkill
        from haven.skills.registry import SkillRegistry

        broken = BaseSkill(
            name="broken",
            description="broken",
            tools=["ghost_tool"],
            default=False,
        )
        SkillRegistry.register_instance(broken)

        result = tool_resolver.resolve(["broken"], channel="cli")
        assert len(result.warnings) > 0

    def test_source_map(self, tool_resolver, register_test_skills):
        """source_map 记录工具来源。"""
        result = tool_resolver.resolve(["coder"], channel="cli")
        assert "code_exec" in result.source_map
        assert result.source_map["code_exec"] == "builtin"


class TestToolResolverFilters:
    """ToolResolver 过滤测试。"""

    def test_permission_filter_respects_granted(self, tool_resolver, register_test_skills):
        """权限过滤 — 内置工具仅有 READ 权限，传入 write 不影响结果。"""
        r1 = tool_resolver.resolve(
            ["coder"], channel="cli", permissions=["read"],
        )
        # 所有内置工具只有 READ 权限，read 授权应全部通过
        assert len(r1.tools) == 3
        assert "code_exec" in r1.tool_names

    def test_no_permission_filter_when_none(self, tool_resolver, register_test_skills):
        """permissions=None 时不过滤。"""
        result = tool_resolver.resolve(["coder"], channel="cli", permissions=None)
        assert len(result.tools) == 3

    def test_invalidate_cache(self, tool_resolver, register_test_skills):
        """清空缓存后重新构建索引。"""
        tool_resolver.invalidate_cache()
        # 之后调用应正常工作
        result = tool_resolver.resolve(["coder"], channel="cli")
        assert len(result.tools) == 3


class TestToolResolverMatching:
    """5 级匹配引擎测试。"""

    def test_match_one_exact(self, tool_resolver):
        """Level 1: 精确名称命中（先 resolve 建立索引）。"""
        # resolve 调用会触发 _build_index
        tool_resolver.resolve(["coder"], channel="cli")
        tool = tool_resolver._match_one("code_exec")
        assert tool is not None
        assert tool.name == "code_exec"

    def test_match_one_unknown(self, tool_resolver):
        """未知需求返回 None。"""
        tool_resolver.resolve(["coder"], channel="cli")
        tool = tool_resolver._match_one("completely_unknown_tool_xyz")
        assert tool is None

    def test_capability_category_map(self):
        """Level 5: _CAPABILITY_CATEGORY 映射覆盖检查。"""
        from haven.tools.resolver import _CAPABILITY_CATEGORY
        from haven.tools.base import ToolCategory

        assert _CAPABILITY_CATEGORY["code"] == ToolCategory.CODE
        assert _CAPABILITY_CATEGORY["file"] == ToolCategory.FILE
        assert _CAPABILITY_CATEGORY["search"] == ToolCategory.SEARCH
        assert _CAPABILITY_CATEGORY["email"] == ToolCategory.COMMUNICATION

    def test_pick_best_prefers_builtin(self, tool_resolver):
        """_pick_best 内置工具优先。"""
        from haven.tools.base import HavenTool, ToolMetadata, ToolCategory

        builtin_tool = MagicHavenTool("test_tool", provider="builtin")
        mcp_tool = MagicHavenTool("test_tool", provider="mcp:github")

        tool_resolver._tag_index["test_tool"] = [builtin_tool, mcp_tool]

        chosen = tool_resolver._pick_best([builtin_tool, mcp_tool], "test_tool")
        assert chosen.metadata.provider == "builtin"


class MagicHavenTool:
    """最小 mock HavenTool。"""
    def __init__(self, name, provider="builtin"):
        self.name = name
        self.metadata = MagicMetadata(provider)


class MagicMetadata:
    def __init__(self, provider):
        self.provider = provider
        self.category = MagicCategory()
        self.permissions = []
        self.tags = []


class MagicCategory:
    value = "custom"
