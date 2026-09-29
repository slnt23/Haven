"""集中式环境配置 —— `.env` 可调项的唯一入口。

只放运行/部署类配置（数据库地址、模型名、日志级别）。
健康与安全相关的医学/合规常量（血压阈值、紧急词表、异常确认窗口、
固定文案等）刻意不在此 —— 它们是产品语义而非部署参数，改动须走
代码评审，不允许被环境变量在部署时悄悄改写。
"""

import logging
from typing import Literal

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from mcp_config import load_mcp_servers

_logger = logging.getLogger(__name__)

#: 开发默认 SQLite；部署须为 PostgreSQL（同一 SQLAlchemy URL 互换）。
DEFAULT_DATABASE_URL = "sqlite+aiosqlite:///./data/haven.db"
#: 默认模型（MDA 格式 <provider>:<model>；.env 的 HAVEN_MODEL 可覆盖）。
DEFAULT_AGENT_MODEL = "deepseek:deepseek-v4-flash"
#: MCP 工具调用的默认超时（秒）——单次外部调用不许拖住整轮对话。
DEFAULT_MCP_TOOL_TIMEOUT = 20.0


class McpServerSettings(BaseModel):
    """一个远程 MCP 服务器的声明。

    平台只支持**远程 HTTP/SSE**（stdio 被 MDA 显式拒绝），所以这里没有
    command/args 之类的字段。`include_tools` 是**只读白名单**：留空则该
    服务器整体不启用（不给模型暴露任何它的工具）。
    """

    transport: Literal["http", "sse"] = "http"
    url: str
    #: 认证等静态请求头（如 {"Authorization": "Bearer …"}）——值放 .env，勿入库。
    headers: dict[str, str] = Field(default_factory=dict)
    #: 允许暴露给模型的远端工具名（白名单，只读工具）。
    include_tools: list[str] = Field(default_factory=list)
    default_tool_timeout: float = DEFAULT_MCP_TOOL_TIMEOUT


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

    @property
    def mcp_servers(self) -> dict[str, McpServerSettings]:
        """已启用的外部 MCP 服务器（校验后）。

        读取交给 `mcp_config.load_mcp_servers()`（标准库实现 —— 连接器模块
        必须在 CLI 的裸解释器里可导入，见其模块头）。配置有问题时**关闭
        MCP**（fail-closed）并留告警：策略层宁可不放行，也不放行没校验过的
        东西。解析结果已缓存，工具调用路径上无重复开销。
        """
        try:
            return {
                name: McpServerSettings(**raw)
                for name, raw in load_mcp_servers().items()
            }
        except Exception as exc:  # noqa: BLE001 —— fail-closed
            _logger.warning("HAVEN_MCP_SERVERS 配置无效，MCP 已关闭：%s", exc)
            return {}


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
