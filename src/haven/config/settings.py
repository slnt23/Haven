"""Settings —— 旧代码兼容层，内部委托给新的 AppConfig 系统。

所有模块最终应直接依赖 AppConfig，不再使用此全局单例。
"""

from __future__ import annotations

from pathlib import Path

from haven.config.loader import load_config
from haven.config.schema import AppConfig


def find_user_path(relative_path: str) -> Path:
    """返回 CWD 下的路径。调用方自行检查是否存在。"""
    return Path.cwd() / relative_path


def get_mcp_config() -> list[dict]:
    """返回来自 mcp.json 的原始 MCP 服务器配置。"""
    from haven.config.mcp import load_mcp_servers
    return load_mcp_servers()


# 延迟加载单例 — 首次访问时按优先级链加载完整配置
_config: AppConfig | None = None


def _get_config() -> AppConfig:
    global _config
    if _config is None:
        _config = load_config()
    return _config


class _SettingsProxy:
    """AppConfig 的代理对象，提供旧模块期望的扁平属性访问。

    daemon_feishu_* 扁平字段映射到嵌套结构，保持旧代码兼容。
    """

    def __getattr__(self, name: str):
        cfg = _get_config()

        # daemon 扁平字段兼容
        if name == "daemon_feishu_enabled":
            return cfg.daemon.feishu.enabled
        if name == "daemon_feishu_app_id":
            return cfg.daemon.feishu.app_id
        if name == "daemon_feishu_app_secret":
            return cfg.daemon.feishu.app_secret

        # Memory 扁平字段兼容
        if name == "memory_enabled":
            return cfg.memory.enabled
        if name == "memory_db_path":
            return cfg.memory.db_path
        if name == "context_window_tokens":
            return cfg.memory.context_window_tokens

        # Skill 扁平字段
        if name == "skill_directory":
            return cfg.skill_directory

        # AppConfig 直接字段
        if name in cfg.model_fields:
            return getattr(cfg, name)

        raise AttributeError(f"'{type(self).__name__}' has no attribute '{name}'")

    def __repr__(self) -> str:
        return repr(_get_config())


settings = _SettingsProxy()
