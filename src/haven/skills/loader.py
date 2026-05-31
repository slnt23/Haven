from __future__ import annotations

from pathlib import Path

import yaml

from .base_skill import BaseSkill


class SkillLoader:
    """Scans a directory for ``*.md`` skill files and builds BaseSkill instances.

    Each ``.md`` file must start with YAML frontmatter delimited by ``---``::

        ---
        name: code_review
        description: Review code for bugs
        trigger_keywords:
          - review
          - 审查
        ---

        You are an expert code reviewer…

    The body after the frontmatter is the skill's prompt extension.
    """

    # ------------------------------------------------------------------
    # public API
    # ------------------------------------------------------------------

    @staticmethod
    def load_from_dir(directory: str | Path) -> list[BaseSkill]:
        directory = Path(directory)
        if not directory.is_dir():
            return []

        skills: list[BaseSkill] = []
        for md_file in sorted(directory.glob("*.md")):
            skill = SkillLoader._parse_file(md_file)
            if skill is not None:
                skills.append(skill)
        return skills

    @staticmethod
    def load_single(filepath: str | Path) -> BaseSkill | None:
        filepath = Path(filepath)
        if not filepath.is_file():
            return None
        return SkillLoader._parse_file(filepath)

    # ------------------------------------------------------------------
    # internal
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_file(filepath: Path) -> BaseSkill | None:
        raw = filepath.read_text(encoding="utf-8")
        frontmatter, body = SkillLoader._split_frontmatter(raw)
        if frontmatter is None:
            return None

        try:
            meta = yaml.safe_load(frontmatter)
        except yaml.YAMLError:
            return None

        if not isinstance(meta, dict):
            return None

        return BaseSkill(
            name=str(meta.get("name", filepath.stem)),
            description=str(meta.get("description", "")),
            prompt=body.strip(),
            trigger_keywords=meta.get("trigger_keywords", []),
            category=str(meta.get("category", "")),
            source_file=filepath,
            default=bool(meta.get("default", False)),
        )

    @staticmethod
    def _split_frontmatter(raw: str) -> tuple[str | None, str]:
        """Return (frontmatter, body) or (None, raw) if no frontmatter found."""
        raw = raw.lstrip()
        if not raw.startswith("---"):
            return None, raw

        # find closing ---
        end = raw.find("---", 3)
        if end == -1:
            return None, raw

        frontmatter = raw[3:end].strip()
        body = raw[end + 3:].strip()
        return frontmatter, body
