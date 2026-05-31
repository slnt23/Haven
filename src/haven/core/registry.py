from typing import Any


class Registry:
    _label: str = "item"

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        cls._items: dict[str, Any] = {}

    @classmethod
    def register(cls, name: str = "") -> Any:
        def decorator(item_cls: Any) -> Any:
            item_name = name or item_cls.__name__.lower()
            cls._items[item_name] = item_cls
            return item_cls

        return decorator

    @classmethod
    def get(cls, name: str) -> Any:
        if name not in cls._items:
            raise KeyError(f"{cls._label} '{name}' not found. Available: {list(cls._items.keys())}")
        return cls._items[name]

    @classmethod
    def list_all(cls) -> list[str]:
        return list(cls._items.keys())

    @classmethod
    def clear(cls) -> None:
        cls._items.clear()
