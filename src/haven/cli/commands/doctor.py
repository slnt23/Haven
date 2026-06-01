"""haven doctor — 环境诊断。"""

from __future__ import annotations

from pathlib import Path
import sys
from typing import Annotated

import typer

from haven.cli.ui.console import (
    blank,
    render_error,
    render_json,
    render_panel,
    render_status,
    render_success,
)

_CHECKS = [
    "python_version",
    "dependencies",
    "config_valid",
    "skills_dir",
    "db_accessible",
    "disk_space",
]


def run_doctor(
    ctx: typer.Context,
    check: Annotated[str | None, typer.Option("--check", help="只检查指定项")] = None,
    json_output: Annotated[bool, typer.Option("--json", "-j", help="JSON 输出")] = False,
) -> None:
    """运行环境诊断，检查依赖和配置完整性。"""
    if check and check not in _CHECKS:
        render_error(f"未知检查项: {check}。可用: {', '.join(_CHECKS)}")
        raise typer.Exit(code=1)

    results: dict[str, dict] = {}
    checks_to_run = [check] if check else _CHECKS

    render_panel("Haven 环境诊断", title="Doctor", style="cyan")
    blank()

    for ck in checks_to_run:
        fn = globals().get(f"_check_{ck}")
        if fn:
            status, msg = fn()
            results[ck] = {"status": "pass" if status else "fail", "message": msg}
            icon = "[green]PASS[/]" if status else "[red]FAIL[/]"
            render_status(icon, f"{ck}: {msg}")

    blank()
    passed = sum(1 for r in results.values() if r["status"] == "pass")
    failed = sum(1 for r in results.values() if r["status"] == "fail")
    if failed == 0:
        render_success(f"全部通过 ({passed}/{len(results)})")
    else:
        render_error(f"{failed} 项未通过, {passed} 项通过")

    if json_output:
        render_json({"checks": results, "summary": {"passed": passed, "failed": failed}})


def _check_python_version() -> tuple[bool, str]:
    v = sys.version_info
    if v >= (3, 14):
        return True, f"Python {v.major}.{v.minor}.{v.micro}"
    return False, f"Python {v.major}.{v.minor}.{v.micro} (>=3.14 required)"


def _check_dependencies() -> tuple[bool, str]:
    required = ["typer", "rich", "langchain_core", "omegaconf", "pydantic", "yaml"]
    missing = [m for m in required if not _try_import(m)]
    if missing:
        return False, f"Missing: {', '.join(missing)}"
    return True, f"Core deps OK ({len(required)})"


def _check_config_valid() -> tuple[bool, str]:
    try:
        from haven.config import settings

        _ = settings.agent_max_iterations
        return True, "app.yaml loaded"
    except Exception as exc:
        return False, f"Config error: {exc}"


def _check_skills_dir() -> tuple[bool, str]:
    skills_dir = Path.cwd() / "skills"
    if skills_dir.is_dir():
        md_files = list(skills_dir.glob("*.md"))
        return True, f"skills/ exists ({len(md_files)} .md files)"
    return False, "skills/ not found"


def _check_db_accessible() -> tuple[bool, str]:
    try:
        db = Path.cwd() / ".data" / "memory.db"
        if db.parent.exists():
            return True, ".data/ accessible"
        db.parent.mkdir(parents=True, exist_ok=True)
        return True, ".data/ created"
    except Exception as exc:
        return False, f"DB path error: {exc}"


def _check_disk_space() -> tuple[bool, str]:
    try:
        import shutil

        usage = shutil.disk_usage(Path.cwd())
        gb = usage.free / (1024**3)
        if gb < 0.1:
            return False, f"Low disk: {gb:.1f}GB free"
        return True, f"{gb:.1f}GB free"
    except Exception:
        return True, "unable to detect"


def _try_import(name: str) -> bool:
    try:
        __import__(name)
        return True
    except ImportError:
        return False
