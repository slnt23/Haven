"""Haven 工具层（Tools / Capability Layer）。

本模块负责工具的 **定义、注册、发现、加载、生命周期管理**，
不负责工具的选择、推理、规划、调度 —— 这些由 Runtime 层和 LLM 自行处理。

设计原则：
  1. 所有工具统一为 ``BaseTool`` 子类，直接传入 ``create_react_agent``
  2. 工具选择完全交给 LLM Function Calling（name + description）
  3. 内置工具放在 ``builtin/`` 目录下，启动时自动扫描发现
  4. MCP 工具通过 ``mcp.json`` 配置，每个服务器一个 Provider

导出：
  - HavenTool       — 工具基类（继承 LangChain BaseTool）
  - ToolMetadata    — 轻量级工具元数据
  - ToolRegistry    — 工具注册中心（纯 CRUD）
  - ToolLoader      — 工具加载器（统一入口）
  - ToolProvider    — 提供者抽象基类
  - BuiltinProvider — 内置工具提供者（自动发现）
  - MCPProvider     — MCP 协议提供者
"""

from haven.tools.base import HavenTool
from haven.tools.loader import ToolLoader
from haven.tools.metadata import ToolMetadata
from haven.tools.providers import (
    BuiltinProvider,
    MCPProvider,
    ProviderInfo,
    ProviderStatus,
    ToolProvider,
)
from haven.tools.registry import ToolRegistry

__all__ = [
    "HavenTool",
    "ToolMetadata",
    "ToolRegistry",
    "ToolLoader",
    "ToolProvider",
    "ProviderInfo",
    "ProviderStatus",
    "BuiltinProvider",
    "MCPProvider",
]
