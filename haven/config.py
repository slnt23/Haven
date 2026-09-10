"""集中式环境配置 —— `.env` 可调项的唯一入口。

只放运行/部署类配置（数据库地址、模型名、日志级别）。
健康与安全相关的医学/合规常量（血压阈值、紧急词表、异常确认窗口、
固定文案等）刻意不在此 —— 它们是产品语义而非部署参数，改动须走
代码评审，不允许被环境变量在部署时悄悄改写。
"""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

#: 开发默认 SQLite；部署须为 PostgreSQL（同一 SQLAlchemy URL 互换）。
DEFAULT_DATABASE_URL = "sqlite+aiosqlite:///./data/haven.db"
#: 默认模型（MDA 格式 <provider>:<model>；.env 的 HAVEN_MODEL 可覆盖）。
DEFAULT_AGENT_MODEL = "deepseek:deepseek-v4-flash"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        # .env 中留空的占位（DATABASE_URL=）不覆盖默认值。
        env_ignore_empty=True,
    )

    database_url: str = DEFAULT_DATABASE_URL
    # validation_alias：环境变量名用 HAVEN_MODEL（字段名默认映射 AGENT_MODEL）。
    agent_model: str = Field(default=DEFAULT_AGENT_MODEL, validation_alias="HAVEN_MODEL")
    #: 本部署唯一服务的用户 id —— **一个部署 = 一个人**（单租户）。
    #: 所有健康数据都记在这个 id 名下；它来自配置而非平台注入，所以本机
    #: `mda dev` 与云端部署是同一个人、同一份数据。不是密钥，改它=换个人用。
    #: 详见 ADR-006 与 `storage/database.py:caller_user_id`。
    owner_id: str = Field(default="owner", validation_alias="HAVEN_OWNER_ID")
    log_level: str = "INFO"


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
