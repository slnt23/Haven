"""MCP 服务器清单（`config/mcp.json`）的**标准库**读取器（单一解析处）。

为什么不能直接用 `config/settings.py`：`connectors/` 下的模块会在 mda 的
各条链路、不同环境里被导入（实测 0.6.1：`mda build` 不加载连接器、模块
顶层报错也构建成功；`mda dev` 会在构建产物运行时加载、失败会打印
traceback；deploy 侧提取环境的依赖更不可控）—— 连接器链路因此只能依赖
标准库：一旦引入 `pydantic_settings` 这类项目依赖，就会出现"有的命令能跑、
有的环境配了却不生效"。同理，**`config/__init__.py` 必须保持为空**：
Python 导入 `config.mcp` 时会先执行包的 `__init__.py`，它一旦引入 pydantic
会以同样方式毁掉连接器加载。本模块只允许 import 标准库。

清单是包内文件（模块相对路径，不依赖 cwd），随项目提交、随构建逐字拷贝
进部署产物。规则：

- 文件缺失 / 空白 / `{}` → 不启用任何服务器（MCP 关闭，不报错）；
- JSON 写错、顶层不是对象、某服务器不是对象 → **大声报错**（配置错误必须
  在构建/启动时暴露）；没配置、或某个服务器没给非空 `include_tools`
  白名单，则不启用该服务器；
- 字符串值支持 `${VAR}` 插值，按 **进程环境 → 项目根 `.env`** 依次解析；
  引用未设置（或为空）的变量 → 大声报错。密钥只放 `.env`，不进仓库。
"""

from __future__ import annotations

import json
import os
import re
from functools import lru_cache
from pathlib import Path
from typing import cast

#: MCP 清单：包内文件，模块相对定位（三种运行方式的 cwd 都成立）。
_MCP_FILE = Path(__file__).resolve().parent / "mcp.json"
#: 插值回落用的项目根 .env（进程环境优先，见 `_lookup`）。
_ENV_FILE = Path(__file__).resolve().parent.parent / ".env"

_VAR_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


@lru_cache(maxsize=1)
def _dotenv() -> dict[str, str]:
    """项目根 `.env` 的朴素解析（仅供 `${VAR}` 回落；读不到 → {}）。

    只处理 `KEY=value` 单行、跳过空行与 `#` 注释、剥成对引号 —— 与
    pydantic-settings 相比刻意保持简单：这里只服务插值取值。
    """
    values: dict[str, str] = {}
    try:
        text = _ENV_FILE.read_text(encoding="utf-8")
    except OSError:
        return values
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.removeprefix("export ").strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key] = value
    return values


def _lookup(name: str) -> str | None:
    """插值取值：进程环境优先（空串按未设置处理），其次项目根 `.env`。"""
    if os.environ.get(name):
        return os.environ[name]
    return _dotenv().get(name) or None


def _substitute(node: object) -> object:
    """递归替换字符串值里的 `${VAR}`；键保持字面量（服务器名不参与插值）。"""
    if isinstance(node, str):

        def replace(match: re.Match[str]) -> str:
            value = _lookup(match.group(1))
            if value is None:
                raise ValueError(
                    f"config/mcp.json 引用了未设置的环境变量 ${{{match.group(1)}}}"
                )
            return value

        return _VAR_PATTERN.sub(replace, node)
    if isinstance(node, dict):
        return {key: _substitute(value) for key, value in node.items()}
    if isinstance(node, list):
        return [_substitute(item) for item in node]
    return node


@lru_cache(maxsize=1)
def load_mcp_servers() -> dict[str, dict[str, object]]:
    """已启用的服务器：``{服务器名: 原始配置字典}``（白名单为空的跳过）。

    结果带缓存（工具调用路径上零重复 IO）；改 `mcp.json` / `.env` 后需重启
    进程才生效。
    """
    try:
        text = _MCP_FILE.read_text(encoding="utf-8")
    except OSError:
        return {}
    if not text.strip():
        return {}
    try:
        parsed = json.loads(text)  # 写错 JSON：在这里直接报错
    except json.JSONDecodeError as exc:
        raise ValueError(f"config/mcp.json JSON 解析失败：{exc}") from exc
    if not isinstance(parsed, dict):
        raise ValueError("config/mcp.json 必须是 JSON 对象（服务器名 -> 配置）")
    # 顶层已校验为 dict，_substitute 对 dict 返回 dict；cast 仅用于类型收窄。
    substituted = cast("dict[str, object]", _substitute(parsed))
    servers: dict[str, dict[str, object]] = {}
    for name, config in substituted.items():
        if not isinstance(config, dict):
            raise ValueError(f"config/mcp.json 中 {name!r} 的配置必须是 JSON 对象")
        include = config.get("include_tools")
        if isinstance(include, list) and include:
            servers[str(name)] = config
    return servers
