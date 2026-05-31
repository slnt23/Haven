from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


# Mapping from standard MCP "type" → internal transport
_TYPE_MAP: dict[str, str] = {
    "stdio": "stdio",
    "sse": "http",
    "streamableHttp": "http",
    "streamable_http": "http",
    "websocket": "websocket",
}


class MCPServerConfig(BaseModel):
    """Configuration for a single MCP server.

    Accepts both the standard ``mcpServers`` entry fields (``type``,
    ``command``, ``args``, ``env``, ``url``, ``headers``) and our
    internal ``transport`` alias.
    """

    name: str
    transport: Literal["stdio", "http", "websocket"] = "stdio"
    enabled: bool = True
    description: str = ""

    # stdio transport
    command: str = ""
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)

    # http / websocket transport
    url: str = ""
    headers: dict[str, str] = Field(default_factory=dict)

    # ---- factory: parse standard mcpServers entry ----

    @classmethod
    def from_standard_entry(cls, name: str, entry: dict[str, Any]) -> "MCPServerConfig":
        """Build config from a standard ``mcpServers`` entry.

        The standard format uses ``type`` (not ``transport``) and
        ``"sse"`` / ``"streamableHttp"`` for HTTP-based servers::

            {
              "type": "stdio",
              "command": "npx",
              "args": ["-y", "package"],
              "env": {"KEY": "value"},
              "enabled": true,
              "description": "..."
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


def load_mcp_servers(path: str | Path | None = None) -> list[dict[str, Any]]:
    """Load MCP server entries from a standard ``mcp.json`` file.

    Returns a list of dicts suitable for ``MCPServerConfig(**entry)``,
    with the standard format already converted to internal field names.
    """
    if path is None:
        from haven.config import find_user_path
        path = find_user_path("mcp/mcp.json")

    config_file = Path(path)
    if not config_file.is_file():
        return []

    with open(config_file, "r", encoding="utf-8") as fh:
        data = json.load(fh)

    servers = data.get("mcpServers", {})
    if not isinstance(servers, dict):
        return []

    result: list[dict[str, Any]] = []
    for name, entry in servers.items():
        cfg = MCPServerConfig.from_standard_entry(name, entry)
        result.append(cfg.model_dump())

    return result
