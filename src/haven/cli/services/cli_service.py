"""CLI 服务 — 全局上下文 + 历史 + 补全。"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class CLIContext:
    """CLI 全局状态容器。在命令生命周期中流动。"""

    # 输出控制
    verbose: bool = False
    quiet: bool = False
    json_output: bool = False
    no_color: bool = False

    # 工作目录
    cwd: Path = field(default_factory=Path.cwd)

    # 命令级配置
    model: str | None = None
    session_id: str | None = None

    # Runtime 引用（重量级命令延迟初始化）
    planner: Any = field(default=None, repr=False)
    runtime: Any = field(default=None, repr=False)

    # 守护进程
    daemon_pid: int | None = None

    @property
    def output_format(self) -> str:
        if self.json_output:
            return "json"
        return "text"


# ====================================================================
# 历史管理
# ====================================================================


class HistoryManager:
    """REPL 命令历史。持久化到 ~/.haven/history。"""

    def __init__(self, max_entries: int = 1000):
        self._max = max_entries
        self._entries: list[str] = []
        self._path = Path.home() / ".haven" / "history"
        self._load()

    def add(self, command: str) -> None:
        self._entries.append(command.strip())
        if len(self._entries) > self._max:
            self._entries = self._entries[-self._max:]
        self._save()

    def search(self, prefix: str) -> list[str]:
        return [e for e in reversed(self._entries) if e.startswith(prefix)]

    def recent(self, n: int = 10) -> list[str]:
        return list(reversed(self._entries[-n:]))

    def _load(self) -> None:
        try:
            if self._path.is_file():
                self._entries = self._path.read_text("utf-8").splitlines()[-self._max:]
        except Exception:
            pass

    def _save(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text("\n".join(self._entries), "utf-8")
        except Exception:
            pass


# ====================================================================
# Tab 补全
# ====================================================================


class TabCompleter:
    """命令补全器。按上下文字典补全。

    用法::

        completer = TabCompleter({"skill": ["coder", "medical"], "model": ["gpt-4o"]})
        matches = completer.complete("haven skill co")  # → ["coder"]
    """

    def __init__(self, completions: dict[str, list[str]] | None = None):
        self._completions: dict[str, list[str]] = completions or {}

    def register(self, category: str, values: list[str]) -> None:
        self._completions[category] = values

    def complete(self, text: str) -> list[str]:
        parts = text.strip().split()
        if len(parts) <= 1:
            return []
        last = parts[-1].lower()
        # 补全命令名
        if len(parts) == 2 and not parts[1].startswith("-"):
            cmds = ["chat", "run", "serve", "stop", "status",
                    "skill", "workflow", "provider", "tool", "model",
                    "memory", "session", "config", "doctor", "version"]
            return [c for c in cmds if c.startswith(last)]
        return [v for v in self._completions.get("all", []) if v.lower().startswith(last)]
