"""Registry — 可注册组件的基类。

子类化后自动获得 ``register`` / ``get`` / ``list_all`` 类方法，
用于 Skill、Workflow 等可扩展组件的统一注册与查找。
"""

from typing import Any


class Registry:
    """可注册组件基类，提供类级别的注册表。

    使用方式::

        class SkillRegistry(Registry):
            _label = "skill"

        @SkillRegistry.register("my_skill")
        class MySkill:
            pass

        skill_cls = SkillRegistry.get("my_skill")
    """

    _label: str = "item"

    def __init_subclass__(cls, **kwargs: Any) -> None:
        """子类化时自动创建空的 ``_items`` 字典。"""
        super().__init_subclass__(**kwargs)
        cls._items: dict[str, Any] = {}

    @classmethod
    def register(cls, name: str = "") -> Any:
        """装饰器：将类注册到注册表。

        若未指定 name，默认使用类名的小写形式。
        """
        def decorator(item_cls: Any) -> Any:
            item_name = name or item_cls.__name__.lower()
            cls._items[item_name] = item_cls
            return item_cls

        return decorator

    @classmethod
    def get(cls, name: str) -> Any:
        """按名称获取已注册的类。不存在时抛出 KeyError。"""
        if name not in cls._items:
            raise KeyError(f"{cls._label} '{name}' not found. Available: {list(cls._items.keys())}")
        return cls._items[name]

    @classmethod
    def list_all(cls) -> list[str]:
        """返回所有已注册组件的名称列表。"""
        return list(cls._items.keys())

    @classmethod
    def clear(cls) -> None:
        """清空注册表（主要用于测试）。"""
        cls._items.clear()
