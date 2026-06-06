"""MCP 配置已迁移至 ``haven.config.mcp``，此文件保留用于向后兼容。"""

from __future__ import annotations

from haven.config.mcp import MCPServerConfig, load_mcp_servers

__all__ = ["MCPServerConfig", "load_mcp_servers"]
