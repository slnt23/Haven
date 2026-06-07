"""Settings — pydantic-settings 配置单例。

配置加载优先级（由低到高）：
1. ``src/haven/config/haven.yaml`` — 内置默认值
2. CWD ``haven.yaml`` — 用户覆盖（OmegaConf deep-merge）
3. 环境变量 — 最高优先级，通过 pydantic-settings Field alias 注入

提供 ``settings`` 全局单例、``find_user_path`` 路径工具和 ``get_mcp_config`` 桥接。
"""

from pathlib import Path

from omegaconf import OmegaConf
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def _find_user_config(filename: str) -> Path | None:
    """在 CWD 中查找用户配置文件。不存在时返回 None。"""
    cwd_path = Path.cwd() / filename
    return cwd_path if cwd_path.is_file() else None


def find_user_path(relative_path: str) -> Path:
    """返回 CWD 下的路径。调用方自行检查是否存在。"""
    return Path.cwd() / relative_path


def _load_app_config() -> dict:
    """加载框架配置：内置 haven.yaml + CWD 用户 haven.yaml deep-merge。"""
    config = OmegaConf.load(Path(__file__).parent / "haven.yaml")
    user_config_path = _find_user_config("haven.yaml")
    if user_config_path is not None:
        config = OmegaConf.merge(config, OmegaConf.load(user_config_path))
    return OmegaConf.to_container(config, resolve=True)


def get_mcp_config() -> list[dict]:
    """返回来自 ``mcp.json`` 的原始 MCP 服务器配置。

    桥接函数：将 settings 模块与 mcp 子模块解耦，避免循环导入。
    """
    from haven.config.mcp import load_mcp_servers

    return load_mcp_servers()


_app_config = _load_app_config()


class Settings(BaseSettings):
    """应用设置单例，字段默认值来自 haven.yaml，可被环境变量覆盖。

    每个字段的 alias 即对应的环境变量名，设置后自动覆盖 YAML 默认值。
    """

    model_config = SettingsConfigDict(extra="ignore")

    # ==================== Agent ====================
    agent_max_iterations: int = Field(
        default=_app_config["agent"]["max_iterations"], alias="AGENT_MAX_ITERATIONS"
    )
    agent_max_execution_time: int = Field(
        default=_app_config["agent"]["max_execution_time"], alias="AGENT_MAX_EXECUTION_TIME"
    )

    # ==================== Web Search ====================
    web_search_api_key: str = Field(default="", alias="WEB_SEARCH_API_KEY")
    web_search_engine: str = Field(
        default=_app_config["web_search"]["engine"], alias="WEB_SEARCH_ENGINE"
    )

    # ==================== RAG ====================
    rag_embedding_model: str = Field(
        default=_app_config["rag"]["embedding_model"], alias="RAG_EMBEDDING_MODEL"
    )
    rag_embedding_api_base: str = Field(
        default=_app_config["rag"]["embedding_api_base"], alias="RAG_EMBEDDING_API_BASE"
    )
    rag_chunk_size: int = Field(default=_app_config["rag"]["chunk_size"], alias="RAG_CHUNK_SIZE")
    rag_chunk_overlap: int = Field(
        default=_app_config["rag"]["chunk_overlap"], alias="RAG_CHUNK_OVERLAP"
    )
    rag_top_k: int = Field(default=_app_config["rag"]["top_k"], alias="RAG_TOP_K")

    # ==================== MCP ====================
    mcp_enabled: bool = Field(default=_app_config["mcp"]["enabled"], alias="MCP_ENABLED")

    # ==================== Daemon ====================
    daemon_feishu_enabled: bool = Field(
        default=_app_config["daemon"]["channels"]["feishu"]["enabled"],
        alias="DAEMON_FEISHU_ENABLED",
    )
    daemon_feishu_app_id: str = Field(
        default=_app_config["daemon"]["channels"]["feishu"]["app_id"], alias="DAEMON_FEISHU_APP_ID"
    )
    daemon_feishu_app_secret: str = Field(
        default=_app_config["daemon"]["channels"]["feishu"]["app_secret"],
        alias="DAEMON_FEISHU_APP_SECRET",
    )

    # ==================== Memory ====================
    memory_enabled: bool = Field(default=_app_config["memory"]["enabled"], alias="MEMORY_ENABLED")
    memory_db_path: str = Field(
        default=_app_config["memory"]["db_path"], alias="MEMORY_DB_PATH"
    )
    context_window_tokens: int = Field(
        default=_app_config["memory"]["context_window_tokens"], alias="CONTEXT_WINDOW_TOKENS"
    )

    # ==================== Skills ====================
    skill_directory: str = Field(default=_app_config["skill"]["directory"], alias="SKILL_DIRECTORY")

    # ==================== Daemon pid ====================
    pid_file: Path = Field(
        default_factory=lambda: (
                Path(__file__).resolve().parent.parent.parent.parent / ".data" / "haven.pid"
        )
    )

    # ==================== Project ====================
    project_root: Path = Path(__file__).resolve().parent.parent.parent.parent


settings = Settings()
