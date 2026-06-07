"""SkillRegistry — Skill 注册、查询、依赖解析。

继承 ``Registry`` 基类，增加：
  - 分类查询（default / domain / by-tag / by-tool）
  - 依赖传递闭包解析
  - LLM 选择上下文格式化
"""

from __future__ import annotations

import logging

from haven.core.registry import Registry
from haven.skills.base_skill import BaseSkill

logger = logging.getLogger("haven.skills")


class SkillRegistry(Registry):
    """Skill 注册表。类级存储，与 ToolRegistry 同风格。

    用法::

        # 加载
        for skill in SkillLoader.load_from_dir("skills/"):
            SkillRegistry.register_instance(skill)

        # 查询
        defaults = SkillRegistry.get_defaults()
        candidates = SkillRegistry.get_domain_skills()
    """

    _label = "Skill"

    # ==================================================================
    # 注册（扩展 Registry 的装饰器模式）
    # ==================================================================

    @classmethod
    def register_instance(cls, skill: BaseSkill) -> None:
        """直接注册 BaseSkill 实例。"""
        cls._items[skill.name] = skill

    @classmethod
    def get(cls, name: str) -> BaseSkill:
        """按名称获取 skill。不存在时抛出 KeyError。"""
        if name not in cls._items:
            raise KeyError(f"{cls._label} '{name}' not found. Available: {list(cls._items.keys())}")
        return cls._items[name]

    @classmethod
    def list_all(cls) -> dict[str, BaseSkill]:
        """返回完整字典 {name: BaseSkill}。"""
        return dict(cls._items)

    # ==================================================================
    # 分类查询
    # ==================================================================

    @classmethod
    def get_defaults(cls) -> dict[str, BaseSkill]:
        """返回所有 ``default=True`` 的人格 skill。"""
        return {
            name: skill for name, skill in cls._items.items() if skill.default
        }

    @classmethod
    def get_domain_skills(cls) -> dict[str, BaseSkill]:
        """返回所有非 default 的领域 skill（供 SkillSelector 候选）。"""
        return {
            name: skill
            for name, skill in cls._items.items()
            if not skill.default
        }

    @classmethod
    def get_by_tag(cls, tag: str) -> dict[str, BaseSkill]:
        """按标签过滤。"""
        return {
            name: skill for name, skill in cls._items.items() if tag in skill.tags
        }

    @classmethod
    def resolve_by_tags(cls, tags: list[str]) -> list[str]:
        """按标签交集匹配 skill，返回名称列表。

        一个 skill 只要其 tags 与输入有任一交集即视为匹配。
        用于工作流节点声明 skill 意图而非硬编码名称。
        """
        matching: list[str] = []
        for name, skill in cls._items.items():
            if any(tag in skill.tags for tag in tags):
                matching.append(name)
        return matching

    @classmethod
    def get_by_tool(cls, tool_name: str) -> dict[str, BaseSkill]:
        """查找使用指定工具的所有 skill。"""
        return {
            name: skill
            for name, skill in cls._items.items()
            if tool_name in skill.tools
        }

    @classmethod
    def get_all_tags(cls) -> list[str]:
        """返回所有 skill 的标签并集（去重排序）。"""
        tags: set[str] = set()
        for skill in cls._items.values():
            tags.update(skill.tags)
        return sorted(tags)

    # ==================================================================
    # 依赖解析
    # ==================================================================

    @classmethod
    def resolve_dependencies(cls, selected: list[str]) -> list[str]:
        """传递闭包解析依赖链。

        选中 skill A (A 依赖 B, B 依赖 C) → 返回 [A, B, C]。

        处理：
          - 传递依赖全部加入
          - 循环依赖检测 + 警告（不阻断）
          - 缺失依赖警告 + 跳过
        """
        result: list[str] = list(selected)
        visited: set[str] = set()

        def _walk(name: str, chain: tuple[str, ...]) -> None:
            if name in visited:
                return
            if name in chain:
                logger.warning("循环依赖: %s", " → ".join(chain) + " → " + name)
                return
            visited.add(name)
            skill = cls._items.get(name)
            if skill is None:
                logger.warning(
                    "依赖 skill 未注册: %s (被 %s 依赖)",
                    name,
                    chain[-1] if chain else "?",
                )
                return
            for dep in skill.dependencies:
                if dep not in result:
                    result.append(dep)
                _walk(dep, (*chain, name))

        for name in list(selected):
            _walk(name, ())

        if len(result) > len(selected):
            logger.info("依赖解析: 自动激活 %s", set(result) - set(selected))

        return result
