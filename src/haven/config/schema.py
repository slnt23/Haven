"""Config Schema —— 所有配置的 Pydantic 数据模型。

模块不得直接读取 YAML，只能依赖这些类型化的 Config 对象。
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ModelConfig(BaseModel):
    """单个模型的配置。

    从 models.yaml 对应条目解析而来，api_key 已从环境变量注入。
    """

    name: str = Field(description="模型名称键，如 'deepseek-v4-pro'")
    provider: str = Field(description="provider 类型: deepseek / openai / aliyun")
    api_key: str = Field(default="", description="从环境变量解析的实际 API Key")
    api_key_env: str = Field(default="", description="声明的环境变量名（仅参考）")
    base_url: str = Field(default="", description="API endpoint")
    temperature: float = Field(default=0.7)
    max_tokens: int = Field(default=4096)


class AgentConfig(BaseModel):
    """单个 Agent 的定义。"""

    name: str
    description: str = ""
    prompt: str = ""


class MemoryConfig(BaseModel):
    """记忆系统配置。"""

    enabled: bool = True
    db_path: str = "resource/memory.db"
    context_window_tokens: int = 8000


class ContextConfig(BaseModel):
    """上下文构建配置。"""

    token_budget: int = 8000
    file_max_tokens: int = 500


class DaemonChannelConfig(BaseModel):
    """守护进程通道配置。"""

    enabled: bool = False
    app_id: str = ""
    app_secret: str = ""


class DaemonConfig(BaseModel):
    """守护进程配置。"""

    feishu: DaemonChannelConfig = Field(default_factory=DaemonChannelConfig)


class AppConfig(BaseModel):
    """Haven 应用完整配置 —— 所有模块的唯一配置入口。

    由 ConfigLoader 按优先级链加载后产出。
    模块通过 DI 获取，不直接读取 YAML。
    """

    # Agent
    agent_max_iterations: int = 20
    agent_max_execution_time: int = 300

    # Models
    default_model: str = "deepseek-v4-pro"
    auxiliary_model: str = "deepseek-v4-flash"
    models: dict[str, ModelConfig] = Field(default_factory=dict)

    # Agents
    agents: dict[str, AgentConfig] = Field(default_factory=dict)

    # Context
    context: ContextConfig = Field(default_factory=ContextConfig)

    # Memory
    memory: MemoryConfig = Field(default_factory=MemoryConfig)

    # Skills
    skill_directory: str = "skills"

    # MCP
    mcp_enabled: bool = True

    # Daemon
    daemon: DaemonConfig = Field(default_factory=DaemonConfig)

    # Web Search
    web_search_engine: str = "bing"
    web_search_api_key: str = ""

    # RAG
    rag_embedding_model: str = "text-embedding-3-small"
    rag_embedding_api_base: str = "https://api.openai.com/v1"
    rag_chunk_size: int = 1000
    rag_chunk_overlap: int = 200
    rag_top_k: int = 5

    # Project
    project_root: str = ""
    pid_file: str = ".data/haven.pid"
