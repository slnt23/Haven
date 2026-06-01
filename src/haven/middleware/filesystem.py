"""文件系统中间件 — 项目文件作为上下文。

将项目目录结构和关键文件自动注入 to state。
当前为占位实现，后续可扫描项目并注入文件列表。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from haven.middleware.base import Middleware


class FilesystemMiddleware(Middleware):
    """项目文件系统上下文中间件。"""

    def __init__(self, workspace: str | Path | None = None):
        self._workspace = Path(workspace) if workspace else None

    async def before_agent(self, state: dict[str, Any]) -> dict[str, Any]:
        if self._workspace is None or not self._workspace.is_dir():
            return state

        # 占位：列出项目关键文件
        patterns = ["*.py", "*.md", "*.yaml", "*.json"]
        files: list[str] = []
        for pat in patterns:
            for f in self._workspace.glob(pat):
                if ".venv" not in str(f) and "__pycache__" not in str(f):
                    files.append(f.relative_to(self._workspace).as_posix())

        if files:
            file_list = "\n".join(f"  - {f}" for f in sorted(files)[:50])
            context = f"[项目文件]\n{file_list}"
            existing = state.get("system_prompt", "")
            state["system_prompt"] = f"{existing}\n\n{context}" if existing else context

        return state
