"""连接器包 —— 目前只有 `mcp.py`（外部 MCP 服务器）。

MDA 按文件名发现连接器：`connectors/<name>.py` 里导出模块级 `connector`
对象（本包只有 `mcp.py`，所以连接器名 = "mcp"；服务器名来自配置键）。
"""
