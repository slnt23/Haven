"""haven skill — Skill 管理。调用 SkillRegistry 获取真实数据。"""

from __future__ import annotations

from typing import Annotated

import typer

from haven.cli.ui.console import (
    blank,
    dim,
    render_error,
    render_info,
    render_json,
    render_success,
    render_table,
    render_warning,
)

skill_app = typer.Typer(help="Skill 增删查 + 热加载")


def _ensure_skills_loaded() -> None:
    """按需加载 skills/ 目录（如尚未加载）。"""
    from haven.skills.registry import SkillRegistry

    if SkillRegistry.list_all():
        return
    from haven.config import find_user_path, settings
    from haven.skills.loader import SkillLoader

    user_dir = find_user_path(settings.skill_directory)
    if user_dir.is_dir():
        for skill in SkillLoader.load_from_dir(user_dir):
            SkillRegistry.register_instance(skill)
    # 系统人格
    from pathlib import Path

    sys_persona = Path(__file__).resolve().parent.parent.parent / "config" / "haven.md"
    if sys_persona.is_file():
        persona = SkillLoader.load_single(sys_persona)
        if persona and persona.name not in SkillRegistry.list_all():
            SkillRegistry.register_instance(persona)


@skill_app.command("list", help="列出所有 skill")
def list_skills(
    ctx: typer.Context,
    default_only: Annotated[bool, typer.Option("--default", help="只列人格 skill")] = False,
    domain_only: Annotated[bool, typer.Option("--domain", help="只列领域 skill")] = False,
    tag: Annotated[str | None, typer.Option("--tag", help="按标签过滤")] = None,
    json_output: Annotated[bool, typer.Option("--json", "-j", help="JSON 输出")] = False,
) -> None:
    """列出已加载的 Skill。"""
    _ensure_skills_loaded()
    try:
        from haven.skills.registry import SkillRegistry

        all_skills = SkillRegistry.list_all()
    except Exception as exc:
        render_error(f"无法获取 Skill: {exc}")
        raise typer.Exit(code=1) from exc

    rows: list[dict] = []
    for name, s in sorted(all_skills.items()):
        skill_type = "人格 (默认)" if s.default else "领域"
        if default_only and not s.default:
            continue
        if domain_only and s.default:
            continue
        if tag and tag.lower() not in " ".join(s.tags).lower():
            continue
        rows.append(
            {
                "Name": name,
                "Type": skill_type,
                "Tags": ", ".join(s.tags) if s.tags else "—",
                "Tools": ", ".join(s.tools) if s.tools else "—",
                "Deps": ", ".join(s.dependencies) if s.dependencies else "—",
                "Version": s.version,
            }
        )

    if json_output:
        render_json(
            [
                {
                    "name": r["Name"],
                    "type": r["Type"],
                    "tags": s.tags,
                    "tools": s.tools,
                    "dependencies": s.dependencies,
                }
                for r, (_, s) in zip(rows, sorted(all_skills.items()), strict=False)
            ]
        )
    else:
        render_table(rows, headers=["Name", "Type", "Tags", "Tools", "Deps", "Version"])
        blank()
        dim(f"共 {len(rows)} 个 skill")


@skill_app.command("info", help="查看 skill 详情")
def info(
    ctx: typer.Context,
    name: Annotated[str, typer.Argument(help="Skill 名")],
    json_output: Annotated[bool, typer.Option("--json", "-j", help="JSON 输出")] = False,
) -> None:
    """查看指定 skill 的详细信息。"""
    _ensure_skills_loaded()
    try:
        from haven.skills.registry import SkillRegistry

        skill = SkillRegistry.get(name)
    except KeyError:
        render_error(f"Skill 不存在: {name}")
        raise typer.Exit(code=1) from None

    if json_output:
        render_json(
            {
                "name": skill.name,
                "description": skill.description,
                "tags": skill.tags,
                "tools": skill.tools,
                "dependencies": skill.dependencies,
                "version": skill.version,
                "default": skill.default,
                "category": skill.category,
            }
        )
    else:
        from haven.cli.ui.console import render_kv

        render_kv(
            [
                ("名称", skill.name),
                ("描述", skill.description or "(无)"),
                ("版本", skill.version),
                ("标签", ", ".join(skill.tags) if skill.tags else "(无)"),
                ("工具", ", ".join(skill.tools) if skill.tools else "(无)"),
                ("依赖", ", ".join(skill.dependencies) if skill.dependencies else "(无)"),
                ("默认", "yes" if skill.default else "no"),
            ]
        )


@skill_app.command("search", help="搜索 skill")
def search(
    ctx: typer.Context,
    query: Annotated[str, typer.Argument(help="搜索词")],
    json_output: Annotated[bool, typer.Option("--json", "-j", help="JSON 输出")] = False,
) -> None:
    """按名称/描述/标签搜索 skill。"""
    _ensure_skills_loaded()
    try:
        from haven.skills.registry import SkillRegistry

        all_skills = SkillRegistry.list_all()
    except Exception as exc:
        render_error(str(exc))
        return

    q = query.lower()
    matched = {
        name: s
        for name, s in all_skills.items()
        if q in name.lower() or q in s.description.lower() or any(q in t.lower() for t in s.tags)
    }

    if json_output:
        render_json(
            [
                {"name": s.name, "description": s.description, "tags": s.tags}
                for s in matched.values()
            ]
        )
    else:
        if not matched:
            render_info(f"未找到匹配 '{query}' 的 skill")
        else:
            rows = [
                {"Name": s.name, "Description": s.description or "—", "Tags": ", ".join(s.tags)}
                for s in matched.values()
            ]
            render_table(rows)
            blank()
            dim(f"找到 {len(matched)} 个")


@skill_app.command("add", help="添加 skill 文件")
def add(
    ctx: typer.Context,
    path: Annotated[str, typer.Argument(help=".md 文件或目录路径")],
    force: Annotated[bool, typer.Option("--force", help="覆盖同名 skill")] = False,
) -> None:
    """从 .md 文件或目录加载 skill。"""
    from pathlib import Path

    from haven.skills.loader import SkillLoader
    from haven.skills.registry import SkillRegistry

    p = Path(path)
    if not p.exists():
        render_error(f"路径不存在: {path}")
        raise typer.Exit(code=1)

    if p.is_file():
        skill = SkillLoader.load_single(p)
        skills = [skill] if skill else []
    else:
        skills = SkillLoader.load_from_dir(p)

    if not skills:
        render_info(f"未找到有效的 skill 文件: {path}")
        return

    added = 0
    for skill in skills:
        if skill.name in SkillRegistry.list_all() and not force:
            render_warning(f"Skill '{skill.name}' 已存在。使用 --force 覆盖。")
            continue
        SkillRegistry.register_instance(skill)
        added += 1
        render_success(f"已添加: {skill.name}")

    blank()
    dim(f"共添加 {added} 个 skill")


@skill_app.command("remove", help="移除 skill")
def remove(
    ctx: typer.Context,
    name: Annotated[str, typer.Argument(help="Skill 名")],
) -> None:
    """按名称移除 skill。"""
    from haven.skills.registry import SkillRegistry

    if name not in SkillRegistry.list_all():
        render_error(f"Skill 不存在: {name}")
        raise typer.Exit(code=1)
    # SkillRegistry 通过 Registry 基类管理，直接操作 _items
    SkillRegistry._items.pop(name, None)
    render_success(f"已移除: {name}")


@skill_app.command("reload", help="热加载 skills/ 目录")
def reload(ctx: typer.Context) -> None:
    """重新扫描 skills/ 目录。"""
    from haven.config import find_user_path, settings
    from haven.skills.loader import SkillLoader
    from haven.skills.registry import SkillRegistry

    user_dir = find_user_path(settings.skill_directory)
    if not user_dir.is_dir():
        render_info(f"skills/ 目录不存在: {user_dir}")
        return

    loaded = SkillLoader.load_from_dir(user_dir)
    for skill in loaded:
        SkillRegistry.register_instance(skill)

    render_success(f"已重新加载 {len(loaded)} 个 skill")
