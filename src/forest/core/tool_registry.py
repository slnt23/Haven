from typing import Any


class ToolRegistry:
    _tools: dict[str, Any] = {}

    @classmethod
    def register(cls, name: str = "") -> Any:
        def decorator(tool_cls: Any) -> Any:
            tool_name = name or tool_cls.__name__.lower()
            cls._tools[tool_name] = tool_cls
            return tool_cls

        return decorator

    @classmethod
    def get(cls, name: str) -> Any:
        if name not in cls._tools:
            raise KeyError(f"Tool '{name}' not found. Available: {list(cls._tools.keys())}")
        return cls._tools[name]

    @classmethod
    def list_tools(cls) -> list[str]:
        return list(cls._tools.keys())

    @classmethod
    def clear(cls) -> None:
        cls._tools.clear()
