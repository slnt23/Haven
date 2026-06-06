"""提供者子包 —— 工具来源实现。

每种工具来源实现一个 ToolProvider 子类：
  - BuiltinProvider — 扫描 ``builtin/`` 目录，自动发现内置工具
  - MCPProvider     — 连接 MCP 服务器，命名空间隔离
"""

from haven.tools.providers.base import ProviderInfo, ProviderStatus, ToolProvider
from haven.tools.providers.builtin import BuiltinProvider
from haven.tools.providers.mcp import MCPProvider

__all__ = [
    "ToolProvider",
    "ProviderInfo",
    "ProviderStatus",
    "BuiltinProvider",
    "MCPProvider",
]
