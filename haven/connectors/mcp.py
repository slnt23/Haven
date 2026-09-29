"""外部 MCP 服务器连接器 —— 声明式接入（平台原生 `connectors.mcp`）。

- 只支持**远程 HTTP/SSE**：MDA 明确拒绝 stdio（"expose the server over HTTP
  or write a normal authored tool instead"），本地 `uvx/npx` 型 MCP 必须先以
  HTTP 方式暴露。
- 服务器清单来自配置（`HAVEN_MCP_SERVERS`，见 `config.py`）而非写死：连接器
  模块由 CLI 在编译期 import，因此可以读 `.env` / 环境变量。
- **只读**：每个服务器必须给出 `include_tools` 白名单；白名单为空的服务器整体
  跳过 —— 宁可没有工具，也不放开写权限。工具调用侧还有
  `middleware/mcp_policy.py` 的兜底拒绝与审计（双保险）。
- `throw_on_load_error=False`：外部服务器不可达时只是"这次没有这些工具"，
  失败不会被缓存（下一轮可重试），绝不因此炸掉整轮健康咨询。

工具在模型侧的名字形如 `{服务器名}__{远端工具名}`（MDA 默认加前缀）。
"""

from __future__ import annotations

from managed_deepagents import connectors

from mcp_config import load_mcp_servers

#: 只读白名单为空的服务器不启用（配置错误时宁可少给能力）。
#: 注意：只用标准库读配置 —— 本模块会被 mda CLI 用它自己的解释器导入
#: （见 `mcp_config.py` 模块头），引入项目依赖会导致整块静默失效。
_servers: dict[str, dict[str, object]] = dict(load_mcp_servers())

# 模块级赋值（不放在 if 里）：mda 的连接器发现可能只认顶层静态可见的
# `connector = ...` 形态；未配置时值为 None，`collect_connectors` 会跳过它
# （MDA 的 mcp 连接器要求「至少一个服务器」，空字典是非法配置，不能传）。
connector = (
    connectors.mcp(
        mcp_servers=_servers,
        prefix_tool_name_with_server_name=True,
        throw_on_load_error=False,
    )
    if _servers
    else None
)
