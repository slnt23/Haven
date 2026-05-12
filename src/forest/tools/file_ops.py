from pathlib import Path

from forest.config import settings
from forest.core.tool_registry import ToolRegistry


@ToolRegistry.register("file_ops")
class FileOpsTool:
    def __init__(self):
        self.work_dir = settings.project_root

    async def read_file(self, path: str | Path) -> str:
        full_path = self.work_dir / path
        return full_path.read_text(encoding="utf-8")

    async def write_file(self, path: str | Path, content: str) -> None:
        full_path = self.work_dir / path
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_text(content, encoding="utf-8")

    async def __call__(self, action: str, path: str, content: str = "") -> str:
        if action == "read":
            return await self.read_file(path)
        elif action == "write":
            await self.write_file(path, content)
            return f"Written: {path}"
        return f"Unknown action: {action}"
