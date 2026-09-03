from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings."""

    model_config = {
        "extra": "ignore",
    }

    database_url: str = "sqlite+aiosqlite:///./db/haven.db"
    log_level: str = "INFO"


    llm_api_key: str | None= Field(default=None, alias="OWL_DEEPSEEK_API_KEY")
    llm_model: str = Field(default="deepseek-v4-flash", alias="LLM_MODEL")