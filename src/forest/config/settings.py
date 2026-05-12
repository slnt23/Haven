from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # LLM
    llm_provider: Literal["openai", "anthropic", "deepseek"] = "openai"
    llm_model: str = "gpt-4o"
    llm_api_key: str = ""
    llm_base_url: str = "https://api.openai.com/v1"
    llm_temperature: float = 0.0
    llm_max_tokens: int = 4096

    # Agent
    agent_max_iterations: int = 20
    agent_max_execution_time: int = 300

    # Tools
    web_search_api_key: str = ""
    web_search_engine: str = "bing"

    # Project
    project_root: Path = Path(__file__).resolve().parent.parent.parent.parent


settings = Settings()
