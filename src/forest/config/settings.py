from pathlib import Path

from omegaconf import OmegaConf
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

_app_config = OmegaConf.to_container(OmegaConf.load(Path(__file__).parent / "app.yaml"), resolve=True)

_env_file = Path(__file__).resolve().parent.parent.parent.parent / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_env_file),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ==================== API Keys ====================
    # 模型 API Key 现在通过 models.yaml 中的 api_key_env 字段指定，
    # 由 loader.get_model_config() 直接从 os.environ 读取。
    # 用户只需在 .env 或 shell 中设置对应环境变量即可，无需修改此文件。

    # ==================== Agent ====================
    agent_max_iterations: int = Field(default=_app_config["agent"]["max_iterations"], alias="AGENT_MAX_ITERATIONS")
    agent_max_execution_time: int = Field(default=_app_config["agent"]["max_execution_time"],
                                          alias="AGENT_MAX_EXECUTION_TIME")

    # ==================== Web Search ====================
    web_search_api_key: str = Field(default="", alias="WEB_SEARCH_API_KEY")
    web_search_engine: str = Field(default=_app_config["web_search"]["engine"], alias="WEB_SEARCH_ENGINE")

    # ==================== Email ====================
    email_smtp_host: str = Field(default=_app_config["email"]["smtp_host"], alias="EMAIL_SMTP_HOST")
    email_smtp_port: int = Field(default=_app_config["email"]["smtp_port"], alias="EMAIL_SMTP_PORT")
    email_smtp_username: str = Field(default="", alias="EMAIL_SMTP_USERNAME")
    email_smtp_password: str = Field(default="", alias="EMAIL_SMTP_PASSWORD")
    email_use_tls: bool = Field(default=_app_config["email"]["use_tls"], alias="EMAIL_USE_TLS")

    email_imap_host: str = Field(default=_app_config["email"]["imap_host"], alias="EMAIL_IMAP_HOST")
    email_imap_port: int = Field(default=_app_config["email"]["imap_port"], alias="EMAIL_IMAP_PORT")
    email_imap_username: str = Field(default="", alias="EMAIL_IMAP_USERNAME")
    email_imap_password: str = Field(default="", alias="EMAIL_IMAP_PASSWORD")
    email_poll_interval: int = Field(default=_app_config["email"]["poll_interval"], alias="EMAIL_POLL_INTERVAL")

    email_user_whitelist: str = Field(default="", alias="EMAIL_USER_WHITELIST")
    email_digest_time: str = Field(default=_app_config["email"]["digest_time"], alias="EMAIL_DIGEST_TIME")

    # ==================== RAG ====================
    rag_embedding_model: str = Field(default=_app_config["rag"]["embedding_model"], alias="RAG_EMBEDDING_MODEL")
    rag_embedding_api_base: str = Field(default=_app_config["rag"]["embedding_api_base"],
                                        alias="RAG_EMBEDDING_API_BASE")
    rag_chunk_size: int = Field(default=_app_config["rag"]["chunk_size"], alias="RAG_CHUNK_SIZE")
    rag_chunk_overlap: int = Field(default=_app_config["rag"]["chunk_overlap"], alias="RAG_CHUNK_OVERLAP")
    rag_top_k: int = Field(default=_app_config["rag"]["top_k"], alias="RAG_TOP_K")

    # ==================== MCP ====================
    mcp_enabled: bool = Field(default=_app_config["mcp"]["enabled"], alias="MCP_ENABLED")

    # ==================== Daemon ====================
    daemon_socket_enabled: bool = Field(default=_app_config["daemon"]["channels"]["socket"]["enabled"],
                                         alias="DAEMON_SOCKET_ENABLED")
    daemon_socket_host: str = Field(default=_app_config["daemon"]["channels"]["socket"]["host"],
                                     alias="DAEMON_SOCKET_HOST")
    daemon_socket_port: int = Field(default=_app_config["daemon"]["channels"]["socket"]["port"],
                                     alias="DAEMON_SOCKET_PORT")
    daemon_email_enabled: bool = Field(default=_app_config["daemon"]["channels"]["email"]["enabled"],
                                        alias="DAEMON_EMAIL_ENABLED")

    # ==================== Memory ====================
    memory_enabled: bool = Field(default=_app_config["memory"]["enabled"], alias="MEMORY_ENABLED")
    memory_extract_after_turn: bool = Field(default=_app_config["memory"]["extract_after_turn"],
                                             alias="MEMORY_EXTRACT_AFTER_TURN")
    memory_min_confidence: float = Field(default=_app_config["memory"]["min_confidence"],
                                          alias="MEMORY_MIN_CONFIDENCE")

    # ==================== Skills ====================
    skill_directory: str = Field(default=_app_config["skill"]["directory"], alias="SKILL_DIRECTORY")

    # ==================== Daemon pid ====================
    pid_file: Path = Field(default_factory=lambda: Path(__file__).resolve().parent.parent.parent.parent / ".data" / "haven.pid")

    # ==================== Project ====================
    project_root: Path = Path(__file__).resolve().parent.parent.parent.parent


settings = Settings()


def get_mcp_config() -> list[dict]:
    """Return raw MCP server configurations from ``mcp.json``."""
    from forest.mcp.config import load_mcp_servers
    return load_mcp_servers()
