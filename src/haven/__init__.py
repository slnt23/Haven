"""Haven — 多智能体交互框架。"""

from __future__ import annotations

try:
    from importlib.metadata import version

    __version__ = version("haven")
except Exception:
    __version__ = "3.0.0"

__all__ = ["__version__"]
