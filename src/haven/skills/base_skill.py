"""BaseSkill — V2 Skill 数据类。

LLM 根据 ``description`` 字段判断是否激活此 skill。
``tags`` + ``tools`` + ``dependencies`` 支持多 skill 组合和依赖解析。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class BaseSkill:
    """由 .md 文件定义的技能——纯数据，零代码。

    LLM 语义选择取代关键词匹配：
    ``description`` 是核心字段，描述 skill 做什么、用什么工具、适用场景。
    """

    name: str
    description: str = ""                       # LLM 选 skill 的核心依据
    prompt: str = ""                            # 正文（注入 system prompt）
    tags: list[str] = field(default_factory=list)            # 分类标签
    tools: list[str] = field(default_factory=list)            # 需要的工具名列表
    dependencies: list[str] = field(default_factory=list)     # 依赖的其他 skill 名
    version: str = "1.0"
    default: bool = False
    category: str = ""
    source_file: Path = field(default_factory=Path)

    # ==================================================================
    # 向后兼容
    # ==================================================================

    @property
    def prompt_extension(self) -> str:
        """兼容 BaseAgent._build_system_prompt() 调用。"""
        return self.prompt

    @property
    def trigger_keywords(self) -> list[str]:
        """已废弃。保留属性避免 V1 引用报错，始终返回空列表。"""
        return []

    def matches(self, task: str) -> bool:
        """已废弃。激活决定权交给 SkillSelector。始终返回 False。"""
        return False

    # ==================================================================
    # 工具查询
    # ==================================================================

    @property
    def tool_set(self) -> set[str]:
        return set(self.tools)

    def requires_tool(self, tool_name: str) -> bool:
        return tool_name in self.tools

    # ==================================================================
    # 表示
    # ==================================================================

    def __repr__(self) -> str:
        return (
            f"<Skill name={self.name!r}"
            f" tags={self.tags} tools={self.tools}"
            f" deps={self.dependencies} default={self.default}>"
        )
