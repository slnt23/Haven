"""MCP 服务器配置解析与验证。

从 CWD 下的 ``mcp.json``（或 ``mcp/mcp.json``）加载 MCP 服务器条目，
将标准 ``mcpServers`` 格式转换为内部 ``MCPServerConfig``，并校验传输层参数。
容错处理 JSON 中的 ``//`` 行注释和尾逗号。
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

# 标准 MCP "type" → 内部 transport 映射
_TYPE_MAP: dict[str, str] = {
    "stdio": "stdio",
    "sse": "http",
    "streamableHttp": "http",
    "streamable_http": "http",
    "websocket": "websocket",
}


class MCPServerConfig(BaseModel):
    """单个 MCP 服务器配置。

    同时接受标准 ``mcpServers`` 条目字段（``type``、``command``、
    ``args``、``env``、``url``、``headers``）和内部 ``transport`` 别名。
    """

    name: str
    transport: Literal["stdio", "http", "websocket"] = "stdio"
    enabled: bool = True
    description: str = ""

    # stdio 传输
    command: str = ""
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)

    # http / websocket 传输
    url: str = ""
    headers: dict[str, str] = Field(default_factory=dict)

    @classmethod
    def from_standard_entry(cls, name: str, entry: dict[str, Any]) -> "MCPServerConfig":
        """从标准 ``mcpServers`` 条目构建配置。

        标准格式使用 ``type``（非 ``transport``），HTTP 服务器使用
        ``"sse"`` / ``"streamableHttp"``::

            {
                "type": "stdio",
                "command": "npx",
                "args": ["-y", "package"],
                "env": {"KEY": "value"},
                "enabled": true,
                "description": "...",
            }
        """
        raw_type = entry.get("type", "stdio")
        transport = _TYPE_MAP.get(raw_type, raw_type)

        return cls(
            name=name,
            transport=transport,
            command=entry.get("command", ""),
            args=entry.get("args", []),
            env=entry.get("env", {}),
            url=entry.get("url", ""),
            headers=entry.get("headers", {}),
            enabled=entry.get("enabled", True),
            description=entry.get("description", ""),
        )

    @model_validator(mode="after")
    def _check_transport_fields(self) -> "MCPServerConfig":
        """校验传输层必填字段：stdio 需要 command，http/ws 需要 url。"""
        if self.transport == "stdio":
            if not self.command:
                raise ValueError(
                    f"MCP server '{self.name}': 'command' is required for stdio transport"
                )
        elif self.transport in ("http", "websocket"):
            if not self.url:
                raise ValueError(
                    f"MCP server '{self.name}': 'url' is required for {self.transport} transport"
                )
        return self


# 预处理正则：移除 // 行注释和尾逗号以容错非标准 JSON
_COMMENT_RE = re.compile(r"^\s*//.*$", re.MULTILINE)
_TRAILING_COMMA_RE = re.compile(r",\s*([}\]])")


def _strip_json_comments(text: str) -> str:
    """去除 JSON 文本中的 // 行注释和尾逗号，使非标准 JSON 可解析。"""
    text = _COMMENT_RE.sub("", text)
    text = _TRAILING_COMMA_RE.sub(r"\1", text)
    return text


def _resolve_mcp_path(path: str | Path | None) -> Path | None:
    """解析 MCP 配置文件路径：CWD/mcp.json 优先，其次 CWD/mcp/mcp.json。"""
    if path is not None:
        candidate = Path(path)
        return candidate if candidate.is_file() else None

    from haven.config import find_user_path

    for relative in ("mcp.json", "mcp/mcp.json"):
        candidate = find_user_path(relative)
        if candidate.is_file():
            return candidate
    return None


def load_mcp_servers(path: str | Path | None = None) -> list[dict[str, Any]]:
    """从 ``mcp.json`` 加载所有 MCP 服务器配置。

    自动查找配置文件、容错解析 JSON 注释、将标准格式转换为内部字段名。

    Args:
        path: 显式指定配置文件路径，为 None 时自动搜索。

    Returns:
        ``MCPServerConfig.model_dump()`` 字典列表。
    """
    config_file = _resolve_mcp_path(path)
    if config_file is None:
        return []

    with open(config_file, "r", encoding="utf-8") as fh:
        raw = _strip_json_comments(fh.read())
        data = json.loads(raw)

    servers = data.get("mcpServers", {})
    if not isinstance(servers, dict):
        return []

    result: list[dict[str, Any]] = []
    for name, entry in servers.items():
        cfg = MCPServerConfig.from_standard_entry(name, entry)
        result.append(cfg.model_dump())

    return result
