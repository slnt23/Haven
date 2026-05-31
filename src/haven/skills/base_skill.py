from __future__ import annotations

from pathlib import Path


class BaseSkill:
    """由 markdown 文件定义的技能——纯数据，零代码。

    每个 .md skill 文件通过 YAML frontmatter 定义元数据；
    正文作为 prompt 扩展注入 agent 的 system prompt。
    """

    def __init__(
        self,
        name: str = "",
        description: str = "",
        prompt: str = "",
        trigger_keywords: list[str] | None = None,
        category: str = "",
        source_file: str | Path = "",
        default: bool = False,
    ) -> None:
        self.name = name
        self.description = description
        self.prompt = prompt
        self.trigger_keywords: list[str] = trigger_keywords or []
        self.category = category
        self.source_file = Path(source_file) if source_file else Path()
        self.default = default

    # ------------------------------------------------------------------
    # prompt_extension — 兼容 BaseAgent._build_system_prompt
    # ------------------------------------------------------------------

    @property
    def prompt_extension(self) -> str:
        return self.prompt

    # ------------------------------------------------------------------
    # 关键词匹配
    # ------------------------------------------------------------------

    def matches(self, task: str) -> bool:
        if not self.trigger_keywords:
            return False
        task_lower = task.lower()
        return any(kw.lower() in task_lower for kw in self.trigger_keywords)

    # ------------------------------------------------------------------
    # 表示
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        return f"<Skill name={self.name!r} category={self.category!r} source={self.source_file.name!r}>"
