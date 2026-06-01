"""BaseSkill + SkillRegistry 测试。"""
from __future__ import annotations

import pytest


class TestBaseSkill:
    """BaseSkill 数据类测试。"""

    def test_default_skill(self):
        from haven.skills.base_skill import BaseSkill
        skill = BaseSkill(name="test")
        assert skill.name == "test"
        assert skill.description == ""
        assert skill.prompt == ""
        assert skill.tags == []
        assert skill.tools == []
        assert skill.dependencies == []
        assert skill.default is False

    def test_skill_with_tools(self):
        from haven.skills.base_skill import BaseSkill
        skill = BaseSkill(
            name="coder",
            description="代码编写",
            tools=["code_exec", "file_ops"],
            tags=["dev"],
        )
        assert skill.tool_set == {"code_exec", "file_ops"}
        assert skill.requires_tool("code_exec") is True
        assert skill.requires_tool("web_search") is False

    def test_prompt_extension_alias(self):
        from haven.skills.base_skill import BaseSkill
        skill = BaseSkill(name="test", prompt="system prompt content")
        assert skill.prompt_extension == "system prompt content"

    def test_repr(self):
        from haven.skills.base_skill import BaseSkill
        skill = BaseSkill(name="test", tags=["a"], tools=["t1"])
        r = repr(skill)
        assert "test" in r
        assert "a" in r


class TestSkillRegistry:
    """SkillRegistry 测试。"""

    @pytest.fixture(autouse=True)
    def clean(self):
        from haven.skills.registry import SkillRegistry
        SkillRegistry.clear()
        yield
        SkillRegistry.clear()

    def _register_sample(self):
        from haven.skills.registry import SkillRegistry
        from haven.skills.base_skill import BaseSkill

        SkillRegistry.register_instance(BaseSkill(
            name="haven", description="人格", prompt="system persona",
            tags=["system"], tools=[], default=True,
        ))
        SkillRegistry.register_instance(BaseSkill(
            name="coder", description="代码", prompt="coding expert",
            tags=["dev", "coding"], tools=["code_exec", "file_ops"],
            default=False,
        ))
        SkillRegistry.register_instance(BaseSkill(
            name="reviewer", description="审查", prompt="review expert",
            tags=["dev"], tools=["code_exec"],
            dependencies=["coder"], default=False,
        ))

    def test_register_and_list(self):
        self._register_sample()
        from haven.skills.registry import SkillRegistry
        all_s = SkillRegistry.list_all()
        assert len(all_s) == 3

    def test_get_existing(self):
        self._register_sample()
        from haven.skills.registry import SkillRegistry
        skill = SkillRegistry.get("coder")
        assert skill.name == "coder"
        assert skill.description == "代码"

    def test_get_missing_raises(self):
        from haven.skills.registry import SkillRegistry
        with pytest.raises(KeyError):
            SkillRegistry.get("nonexistent")

    def test_get_defaults(self):
        self._register_sample()
        from haven.skills.registry import SkillRegistry
        defaults = SkillRegistry.get_defaults()
        assert len(defaults) == 1
        assert "haven" in defaults

    def test_get_domain_skills(self):
        self._register_sample()
        from haven.skills.registry import SkillRegistry
        domain = SkillRegistry.get_domain_skills()
        assert len(domain) == 2
        assert "haven" not in domain

    def test_get_by_tag(self):
        self._register_sample()
        from haven.skills.registry import SkillRegistry
        dev_skills = SkillRegistry.get_by_tag("dev")
        assert len(dev_skills) == 2

    def test_get_by_tool(self):
        self._register_sample()
        from haven.skills.registry import SkillRegistry
        code_skills = SkillRegistry.get_by_tool("code_exec")
        assert len(code_skills) == 2

    def test_get_all_tags(self):
        self._register_sample()
        from haven.skills.registry import SkillRegistry
        tags = SkillRegistry.get_all_tags()
        assert "dev" in tags
        assert "coding" in tags
        assert "system" in tags

    def test_resolve_dependencies_transitive(self):
        self._register_sample()
        from haven.skills.registry import SkillRegistry
        resolved = SkillRegistry.resolve_dependencies(["reviewer"])
        assert "reviewer" in resolved
        assert "coder" in resolved  # reviewer → coder 传递

    def test_resolve_no_deps(self):
        self._register_sample()
        from haven.skills.registry import SkillRegistry
        resolved = SkillRegistry.resolve_dependencies(["coder"])
        assert resolved == ["coder"]

    def test_get_selection_context(self):
        self._register_sample()
        from haven.skills.registry import SkillRegistry
        ctx = SkillRegistry.get_selection_context()
        assert "coder" in ctx
        assert "reviewer" in ctx
        assert "haven" not in ctx  # 只包含领域 skill
