"""MCP 服务器清单的**标准库**读取器（单一解析处）。

为什么不能直接用 `config.py`：`connectors/` 下的模块由 mda CLI 在编译期用
**它自己的解释器**导入，而那个环境没有 `pydantic_settings` 等项目依赖 ——
连接器链路因此只能依赖标准库。用 `config.py` 会让模块导入失败，而 CLI 对
导入失败的连接器模块是**静默跳过**的（表现为"配了却完全不生效"）。

取值顺序与 pydantic-settings 一致：进程环境优先，其次项目根的 `.env`
（只支持单行 `HAVEN_MCP_SERVERS=<JSON>`；留空 = 未配置）。
JSON 写错**大声报错**（配置错误必须在构建/启动时暴露）；没配置、
或某个服务器没给非空 `include_tools` 白名单，则不启用该服务器。
"""

from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path

ENV_KEY = "HAVEN_MCP_SERVERS"
_ENV_FILE = Path(".env")


def _raw_value() -> str | None:
    value = os.environ.get(ENV_KEY)
    if value is not None and value.strip():
        return value.strip()
    try:
        for line in _ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith(f"{ENV_KEY}="):
                candidate = line.split("=", 1)[1].strip()
                return candidate or None
    except OSError:
        return None
    return None


@lru_cache(maxsize=1)
def load_mcp_servers() -> dict[str, dict[str, object]]:
    """已启用的服务器：``{服务器名: 原始配置字典}``（白名单为空的跳过）。"""
    raw = _raw_value()
    if not raw:
        return {}
    parsed = json.loads(raw)  # 写错 JSON：在这里直接报错
    if not isinstance(parsed, dict):
        raise ValueError(f"{ENV_KEY} 必须是 JSON 对象（服务器名 -> 配置）")
    servers: dict[str, dict[str, object]] = {}
    for name, config in parsed.items():
        if not isinstance(config, dict):
            raise ValueError(f"{ENV_KEY} 中 {name!r} 的配置必须是 JSON 对象")
        include = config.get("include_tools")
        if isinstance(include, list) and include:
            servers[str(name)] = config
    return servers
