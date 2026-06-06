"""Config 模块 — 框架配置层。

负责加载和管理所有配置来源：
- ``haven.yaml`` — 内置默认 + 用户 CWD 覆盖（OmegaConf deep-merge）
- ``models.yaml`` — 模型定义，含 provider / API Key 环境变量映射
- ``mcp.json`` — MCP 服务器连接配置
- 环境变量 — 最高优先级，通过 pydantic-settings 注入

对外暴露 ``settings`` 单例、模型配置查询和 MCP 配置加载。
"""

from .loader import get_auxiliary_model, get_default_model, get_model_config, load_models_config
from .settings import find_user_path, get_mcp_config, settings

__all__ = [
    "settings",
    "get_mcp_config",
    "find_user_path",
    "load_models_config",
    "get_model_config",
    "get_auxiliary_model",
    "get_default_model",
]
