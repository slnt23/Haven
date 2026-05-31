from __future__ import annotations

from pathlib import Path

import yaml

from .base_skill import BaseSkill


class SkillLoader:
    """扫描目录中的 ``*.md`` skill 文件并构建 BaseSkill 实例。

    每个 ``.md`` 文件必须以 ``---`` 分隔的 YAML frontmatter 开头::

        ---
        name: code_review
        description: Review code for bugs
        trigger_keywords:
          - review
          - 审查
        ---

        You are an expert code reviewer…

    frontmatter 之后的正文为 skill 的 prompt 扩展。
    """

    # ------------------------------------------------------------------
    # 公开 API
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
    # 内部实现
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
        """返回 (frontmatter, body)，无 frontmatter 时返回 (None, raw)。"""
        raw = raw.lstrip()
        if not raw.startswith("---"):
            return None, raw

        # 查找闭合的 ---
        end = raw.find("---", 3)
        if end == -1:
            return None, raw

        frontmatter = raw[3:end].strip()
        body = raw[end + 3:].strip()
        return frontmatter, body
