from typing import Any


class SkillRegistry:
    """Decorator-based registry for skills (same pattern as ToolRegistry)."""

    _skills: dict[str, Any] = {}

    @classmethod
    def register(cls, name: str = "") -> Any:
        def decorator(skill_cls: Any) -> Any:
            skill_name = name or skill_cls.__name__.lower()
            cls._skills[skill_name] = skill_cls
            return skill_cls

        return decorator

    @classmethod
    def get(cls, name: str) -> Any:
        if name not in cls._skills:
            raise KeyError(
                f"Skill '{name}' not found. Available: {list(cls._skills.keys())}"
            )
        return cls._skills[name]

    @classmethod
    def list_skills(cls) -> list[str]:
        return list(cls._skills.keys())

    @classmethod
    def clear(cls) -> None:
        cls._skills.clear()
