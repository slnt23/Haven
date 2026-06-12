"""Config 模块 —— 框架配置层。

提供：
  - ConfigLoader / load_config() —— 新配置系统（推荐）
  - AppConfig / ModelConfig / AgentConfig —— 类型化配置对象
  - settings / find_user_path —— 旧代码兼容（Phase 6 后移除）
"""

# ---- 新 API -----------------------------------------------------------
from haven.config.schema import AgentConfig, AppConfig, ContextConfig, MemoryConfig, ModelConfig
from haven.config.loader import ConfigLoader, load_config

# ---- 旧代码兼容 ---------------------------------------------------------
from haven.config.settings import find_user_path, get_mcp_config, settings
from haven.config.loader import (
    get_auxiliary_model,
    get_default_model,
    get_model_config,
    load_models_config,
)

__all__ = [
    # New
    "AppConfig",
    "ModelConfig",
    "AgentConfig",
    "ContextConfig",
    "MemoryConfig",
    "ConfigLoader",
    "load_config",
    # Legacy (remove after Phase 6)
    "settings",
    "get_mcp_config",
    "find_user_path",
    "load_models_config",
    "get_model_config",
    "get_auxiliary_model",
    "get_default_model",
]
