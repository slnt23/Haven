from pathlib import Path
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    _env_file = Path(__file__).resolve().parent.parent.parent.parent / ".env"

    model_config = SettingsConfigDict(
        env_file=str(_env_file),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ==================== API Keys ====================
    deepseek_api_key: str = Field(default="", alias="DEEPSEEK_API_KEY")
    openai_api_key: str = Field(default="", alias="OPENAI_API_KEY")

    # ==================== Agent Defaults ====================
    agent_default_model: str = Field(default="deepseek-v4-pro", alias="AGENT_DEFAULT_MODEL")
    agent_max_iterations: int = Field(default=20, alias="AGENT_MAX_ITERATIONS")
    agent_max_execution_time: int = Field(default=300, alias="AGENT_MAX_EXECUTION_TIME")

    # ==================== Tools - Web Search ====================
    web_search_api_key: str = Field(default="", alias="WEB_SEARCH_API_KEY")
    web_search_engine: str = Field(default="bing", alias="WEB_SEARCH_ENGINE")

    # ==================== Project ====================
    project_root: Path = Path(__file__).resolve().parent.parent.parent.parent


# 实例化
settings = Settings()
