"""WorkflowRegistry —— 工作流注册与发现。"""

from __future__ import annotations

from typing import Any


class WorkflowRegistry:
    """工作流注册表。

    注册的 factory 函数返回编译后的 LangGraph StateGraph 实例。
    """

    _label = "Workflow"
    _items: dict[str, Any] = {}

    @classmethod
    def register(cls, name: str) -> Any:
        def decorator(factory: Any) -> Any:
            cls._items[name] = factory
            return factory
        return decorator

    @classmethod
    def get(cls, name: str) -> Any:
        if name not in cls._items:
            raise KeyError(f"Workflow '{name}' not found. Available: {list(cls._items.keys())}")
        return cls._items[name]

    @classmethod
    def list_all(cls) -> list[str]:
        return list(cls._items.keys())

    @classmethod
    def build(cls, name: str) -> Any:
        factory = cls.get(name)
        return factory()

    @classmethod
    def get_selection_context(cls) -> str:
        if not cls._items:
            return "(无可用工作流)"
        lines: list[str] = []
        for name, factory in cls._items.items():
            desc = ""
            use_cases = ""
            step_count = "?"
            if hasattr(factory, "description"):
                desc = factory.description
            elif hasattr(factory, "__doc__") and factory.__doc__:
                desc = factory.__doc__.strip().split("\n")[0]
            if hasattr(factory, "use_cases"):
                use_cases = factory.use_cases
            if hasattr(factory, "step_count"):
                step_count = str(factory.step_count)
            lines.append(f"- name: {name}")
            lines.append(f"  description: {desc}")
            if use_cases:
                lines.append(f"  use_cases: {use_cases}")
            lines.append(f"  steps: {step_count}")
        return "\n".join(lines)

    @classmethod
    def clear(cls) -> None:
        cls._items.clear()
