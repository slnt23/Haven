from __future__ import annotations

from pathlib import Path


class BaseSkill:
    """A skill defined by a markdown file — pure data, no code required.

    Each .md skill file has YAML frontmatter for metadata; the body is the
    prompt extension injected into the agent's system prompt.
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
    # prompt_extension — for compatibility with BaseAgent._build_system_prompt
    # ------------------------------------------------------------------

    @property
    def prompt_extension(self) -> str:
        return self.prompt

    # ------------------------------------------------------------------
    # keyword matching
    # ------------------------------------------------------------------

    def matches(self, task: str) -> bool:
        if not self.trigger_keywords:
            return False
        task_lower = task.lower()
        return any(kw.lower() in task_lower for kw in self.trigger_keywords)

    # ------------------------------------------------------------------
    # representation
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        return f"<Skill name={self.name!r} category={self.category!r} source={self.source_file.name!r}>"
