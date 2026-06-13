"""ContextBuilder — 统一上下文构建，替代 Middleware 管道拼贴 prompt。

按优先级 + token 预算组装 system_prompt:
  ① Personality (haven.md, 固定)
  ② Agent prompt (每种 Agent 的专属指令)
  ③ Skills prompt (激活技能的 .md prompt 字段)
  ④ Project files (≤500 token)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from haven.config import load_config

logger = logging.getLogger("haven.context")

_PERSONA_PATH = Path(__file__).resolve().parent.parent / "config" / "haven.md"

# ============================================================================
# Channel-Aware Response Hints
# ============================================================================

_CHANNEL_HINTS: dict[str, str] = {
    "cli": (
        "[Output Environment]\n"
        "You are communicating via a terminal (channel=cli). "
        "Format your response for terminal display: use plain paragraphs, "
        "numbered or bullet lists, and indentation. "
        "Do NOT use Markdown tables (|---|---|), horizontal rules (---), "
        "or multi-level headings (###). "
        "Code blocks (```) are acceptable. "
        "IMPORTANT: if the user explicitly requests Markdown, HTML, JSON, code, "
        "or any specific format, ALWAYS follow the user's request - "
        "the user's request overrides this environment preference."
    ),
    "web": (
        "[Output Environment]\n"
        "You are replying via web (channel=web). Standard Markdown is fully supported "
        "and encouraged for readability."
    ),
    "api": (
        "[Output Environment]\n"
        "You are replying via API (channel=api). Prefer structured, machine-readable "
        "responses. Avoid formatting that depends on visual rendering."
    ),
}


def _load_persona() -> str:
    """读取 haven.md 并剥离 YAML frontmatter。

    haven.md 格式：
        ---
        name: haven
        ...
        ---
        ## 角色：健健 — 灯塔医疗助手机器人
        ...

    仅返回第二个 ``---`` 之后的人格正文。
    """
    if not _PERSONA_PATH.is_file():
        return ""
    raw = _PERSONA_PATH.read_text(encoding="utf-8").strip()
    if raw.startswith("---"):
        parts = raw.split("---", 2)
        if len(parts) >= 3:
            return parts[2].strip()
    return raw


@dataclass
class BuildResult:
    system_prompt: str = ""
    token_usage: dict[str, int] = field(default_factory=dict)


class ContextBuilder:
    """统一构建 LLM 上下文。"""

    def __init__(self, token_budget: int | None = None):
        self.token_budget = token_budget or load_config().context.token_budget
        self._persona = _load_persona()

    def build(
        self,
        *,
        agent_prompt: str = "",
        skills: list[Any] | None = None,
        task: str = "",
        history_summary: str = "",
        channel: str = "",
    ) -> BuildResult:
        """按优先级组装 system_prompt。

        优先级: Personality > Agent prompt > Skills > Project files > History > Channel hint
        """
        budget = self.token_budget
        parts: list[str] = []
        usage: dict[str, int] = {}

        # ① Personality (固定)
        if self._persona:
            parts.append(self._persona)
            usage["personality"] = self._estimate_tokens(self._persona)

        # ② Agent prompt
        if agent_prompt:
            parts.append(agent_prompt)
            usage["agent"] = self._estimate_tokens(agent_prompt)

        # ③ Skills prompt
        skill_text = self._build_skill_prompt(skills or [])
        if skill_text:
            # 技能 prompt 最多占剩余预算的 60%
            skill_budget = int((budget - self._parts_tokens(parts)) * 0.6)
            if self._estimate_tokens(skill_text) > skill_budget:
                skill_text = self._truncate(skill_text, skill_budget)
            parts.append(skill_text)
            usage["skills"] = self._estimate_tokens(skill_text)

        # ④ Project files (≤500 token)
        used = self._parts_tokens(parts)
        file_budget = min(500, budget - used - 200)
        if file_budget > 0:
            file_text = self._list_files(max_tokens=file_budget)
            if file_text:
                parts.append(file_text)
                usage["files"] = self._estimate_tokens(file_text)

        # ⑤ History summary (剩余预算)
        if history_summary:
            remaining = budget - self._parts_tokens(parts) - 100
            if remaining > 0:
                if self._estimate_tokens(history_summary) > remaining:
                    history_summary = self._truncate(history_summary, remaining)
                parts.append(history_summary)
                usage["history"] = self._estimate_tokens(history_summary)

        # ⑥ Channel hint (输出环境适配)
        hint = _CHANNEL_HINTS.get(channel, "")
        if hint:
            parts.append(hint)
            usage["channel"] = self._estimate_tokens(hint)

        result = BuildResult(
            system_prompt="\n\n".join(parts),
            token_usage=usage,
        )
        logger.debug("Context built: %s", {k: v for k, v in usage.items()})
        return result

    # ==================================================================
    # Internal
    # ==================================================================

    def _build_skill_prompt(self, skills: list[Any]) -> str:
        prompts: list[str] = []
        for s in skills:
            prompt = getattr(s, "prompt", None)
            if prompt:
                prompts.append(prompt)
        return "\n\n".join(prompts)

    def _list_files(self, max_tokens: int = 500) -> str:
        ws = load_config().project_root
        if not ws or not Path(ws).is_dir():
            return ""

        files: list[str] = []
        for pattern in ["*.py", "*.md", "*.yaml", "*.json"]:
            for f in Path(ws).rglob(pattern):
                if ".venv" in f.parts or "__pycache__" in f.parts:
                    continue
                files.append(str(f.relative_to(ws)))

        lines = ["[项目文件]"]
        tokens = 20  # 标题 token
        for f in sorted(files)[:50]:
            line = f"- {f}"
            t = self._estimate_tokens(line)
            if tokens + t > max_tokens:
                break
            lines.append(line)
            tokens += t

        return "\n".join(lines) if len(lines) > 1 else ""

    @staticmethod
    def _estimate_tokens(text: str) -> int:
        return len(text) // 3

    @staticmethod
    def _parts_tokens(parts: list[str]) -> int:
        return sum(len(p) // 3 for p in parts) + len(parts) * 2

    @staticmethod
    def _truncate(text: str, max_tokens: int) -> str:
        max_chars = max_tokens * 3
        if len(text) <= max_chars:
            return text
        return text[:max_chars - 3] + "..."
