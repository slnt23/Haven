import subprocess
import sys
import tempfile
from pathlib import Path

from haven.tools.tool_registry import ToolRegistry


@ToolRegistry.register("code_exec")
class CodeExecTool:
    def __init__(self):
        self.timeout = 30

    async def run_python(self, code: str) -> str:
        with tempfile.TemporaryDirectory() as tmp:
            filepath = Path(tmp) / "script.py"
            filepath.write_text(code, encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(filepath)],
                capture_output=True, text=True, timeout=self.timeout,
            )
            return result.stdout + result.stderr

    async def run_shell(self, command: str) -> str:
        result = subprocess.run(
            command, capture_output=True, text=True,
            timeout=self.timeout, shell=True,
        )
        return result.stdout + result.stderr

    async def __call__(self, language: str, code: str) -> str:
        if language == "python":
            return await self.run_python(code)
        return f"Unsupported language: {language}"
