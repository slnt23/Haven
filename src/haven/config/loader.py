"""ConfigLoader —— 按优先级链加载全部配置，产出类型化的 AppConfig。

优先级（由低到高）：
  1. 内置 haven.yaml / models.yaml（src/haven/config/）
  2. 用户 haven.yaml / models.yaml（CWD）— OmegaConf deep-merge
  3. 环境变量 — HAVEN_ 前缀或字段别名
  4. 运行时覆盖 — load() 的 overrides 参数

模块不得直接读取 YAML。依赖方通过 AppConfig 对象获取所有配置。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from omegaconf import OmegaConf

from haven.config.schema import (
    AgentConfig,
    AppConfig,
    ContextConfig,
    DaemonChannelConfig,
    DaemonConfig,
    MemoryConfig,
    ModelConfig,
)

# ============================================================================
# 文件路径
# ============================================================================

_BUILTIN_DIR = Path(__file__).resolve().parent
_DEFAULT_YAML = _BUILTIN_DIR / "haven.yaml"
_MODELS_YAML = _BUILTIN_DIR / "models.yaml"


def _find_user_file(filename: str) -> Path | None:
    """在 CWD 中查找用户配置文件。"""
    path = Path.cwd() / filename
    return path if path.is_file() else None


# ============================================================================
# 环境变量映射
# ============================================================================

# (env_var, dotted_path) — 覆盖 AppConfig 的对应字段
# Env var → YAML nested path (matches haven.yaml structure)
_ENV_OVERRIDES: list[tuple[str, str]] = [
    ("AGENT_MAX_ITERATIONS", "agent.max_iterations"),
    ("AGENT_MAX_EXECUTION_TIME", "agent.max_execution_time"),
    ("WEB_SEARCH_API_KEY", "web_search.api_key"),
    ("WEB_SEARCH_ENGINE", "web_search.engine"),
    ("RAG_EMBEDDING_MODEL", "rag.embedding_model"),
    ("RAG_EMBEDDING_API_BASE", "rag.embedding_api_base"),
    ("RAG_CHUNK_SIZE", "rag.chunk_size"),
    ("RAG_CHUNK_OVERLAP", "rag.chunk_overlap"),
    ("RAG_TOP_K", "rag.top_k"),
    ("MCP_ENABLED", "mcp.enabled"),
    ("MEMORY_ENABLED", "memory.enabled"),
    ("MEMORY_DB_PATH", "memory.db_path"),
    ("CONTEXT_WINDOW_TOKENS", "memory.context_window_tokens"),
    ("SKILL_DIRECTORY", "skill.directory"),
    ("DAEMON_FEISHU_ENABLED", "daemon.channels.feishu.enabled"),
    ("DAEMON_FEISHU_APP_ID", "daemon.channels.feishu.app_id"),
    ("DAEMON_FEISHU_APP_SECRET", "daemon.channels.feishu.app_secret"),
]


def _set_nested(data: dict, dotted_path: str, value: Any) -> None:
    """按点分隔路径设置嵌套字典值，如 'memory.enabled' → data['memory']['enabled']。"""
    parts = dotted_path.split(".")
    for part in parts[:-1]:
        data = data.setdefault(part, {})
    data[parts[-1]] = value


def _apply_env_overrides(data: dict[str, Any]) -> dict[str, Any]:
    """将环境变量覆盖到配置字典中（类型转换后的值）。"""
    for env_var, path in _ENV_OVERRIDES:
        raw = os.environ.get(env_var)
        if raw is None:
            continue
        # 类型推断：尝试 int / float / bool，回退到 str
        value: Any = raw
        if raw.lower() in ("true", "false"):
            value = raw.lower() == "true"
        else:
            try:
                value = int(raw)
            except ValueError:
                try:
                    value = float(raw)
                except ValueError:
                    pass
        _set_nested(data, path, value)
    return data


# ============================================================================
# YAML 加载
# ============================================================================


def _load_yaml_with_merge(
    default_path: Path,
    user_filename: str,
) -> dict[str, Any]:
    """加载默认 YAML，若 CWD 有同名文件则 deep-merge 覆盖。"""
    cfg = OmegaConf.load(default_path)
    user_path = _find_user_file(user_filename)
    if user_path is not None:
        cfg = OmegaConf.merge(cfg, OmegaConf.load(user_path))
    return OmegaConf.to_container(cfg, resolve=True)  # type: ignore[return-value]


def _load_models_config() -> dict[str, ModelConfig]:
    """加载 models.yaml → dict[name, ModelConfig]（API Key 已从环境变量注入）。"""
    raw = _load_yaml_with_merge(_MODELS_YAML, "models.yaml")
    models_raw = raw.get("models", {})

    result: dict[str, ModelConfig] = {}
    for name, entry in models_raw.items():
        if not isinstance(entry, dict):
            continue
        api_key_env = str(entry.get("api_key_env", ""))
        api_key = os.environ.get(api_key_env, "")
        result[name] = ModelConfig(
            name=name,
            provider=str(entry.get("provider", "")),
            api_key=api_key,
            api_key_env=api_key_env,
            base_url=str(entry.get("base_url", "")),
            temperature=float(entry.get("temperature", 0.7)),
            max_tokens=int(entry.get("max_tokens", 4096)),
        )
    return result


# ============================================================================
# ConfigLoader
# ============================================================================


class ConfigLoader:
    """配置加载器 —— 唯一 YAML 读取入口。

    外部模块不应直接调用此类 —— 通过 load_config() 便捷函数获取 AppConfig。
    """

    @staticmethod
    def load(*, overrides: dict[str, Any] | None = None) -> AppConfig:
        """按优先级链加载配置，返回不可变的 AppConfig。

        优先级：内置 YAML < 用户 YAML < 环境变量 < 运行时 overrides
        """
        # ---- 1. 加载 haven.yaml (app config) ---------------------------------
        app_raw = _load_yaml_with_merge(_DEFAULT_YAML, "haven.yaml")

        # ---- 2. 加载 models.yaml ---------------------------------------------
        models_raw = _load_yaml_with_merge(_MODELS_YAML, "models.yaml")
        models = _load_models_config()
        default_model = str(models_raw.get("default_model", "deepseek-v4-pro"))
        aux_model = str(models_raw.get("auxiliary_model", default_model))

        # ---- 3. 环境变量覆盖 -------------------------------------------------
        app_raw = _apply_env_overrides(app_raw)

        # ---- 4. 构建 AppConfig -----------------------------------------------
        config = AppConfig(
            agent_max_iterations=int(app_raw.get("agent", {}).get("max_iterations", 20)),
            agent_max_execution_time=int(app_raw.get("agent", {}).get("max_execution_time", 300)),
            default_model=str(default_model),
            auxiliary_model=str(aux_model),
            models=models,
            agents={
                name: AgentConfig(
                    name=name,
                    description=str(cfg.get("description", "")),
                    prompt=str(cfg.get("prompt", "")),
                )
                for name, cfg in app_raw.get("agents", {}).items()
                if isinstance(cfg, dict)
            },
            context=ContextConfig(
                token_budget=int(app_raw.get("context", {}).get("token_budget", 8000)),
                file_max_tokens=int(app_raw.get("context", {}).get("file_max_tokens", 500)),
            ),
            memory=MemoryConfig(
                enabled=bool(app_raw.get("memory", {}).get("enabled", True)),
                db_path=str(app_raw.get("memory", {}).get("db_path", "resource/memory.db")),
                context_window_tokens=int(app_raw.get("memory", {}).get("context_window_tokens", 8000)),
            ),
            skill_directory=str(app_raw.get("skill", {}).get("directory", "skills")),
            mcp_enabled=bool(app_raw.get("mcp", {}).get("enabled", True)),
            daemon=DaemonConfig(
                feishu=DaemonChannelConfig(
                    enabled=bool(app_raw.get("daemon", {}).get("channels", {}).get("feishu", {}).get("enabled", False)),
                    app_id=str(app_raw.get("daemon", {}).get("channels", {}).get("feishu", {}).get("app_id", "")),
                    app_secret=str(app_raw.get("daemon", {}).get("channels", {}).get("feishu", {}).get("app_secret", "")),
                ),
            ),
            web_search_engine=str(app_raw.get("web_search", {}).get("engine", "bing")),
            web_search_api_key=str(app_raw.get("web_search", {}).get("api_key", "")),
            rag_embedding_model=str(app_raw.get("rag", {}).get("embedding_model", "text-embedding-3-small")),
            rag_embedding_api_base=str(app_raw.get("rag", {}).get("embedding_api_base", "")),
            rag_chunk_size=int(app_raw.get("rag", {}).get("chunk_size", 1000)),
            rag_chunk_overlap=int(app_raw.get("rag", {}).get("chunk_overlap", 200)),
            rag_top_k=int(app_raw.get("rag", {}).get("top_k", 5)),
            project_root=str(Path.cwd()),
            pid_file=str(app_raw.get("pid_file", ".data/haven.pid")),
        )

        # ---- 5. 运行时覆盖 ---------------------------------------------------
        if overrides:
            config = config.model_copy(update=overrides)

        return config


# ============================================================================
# 便捷函数
# ============================================================================


def load_config(*, overrides: dict[str, Any] | None = None) -> AppConfig:
    """按优先级链加载配置。

    外部模块的唯一配置入口。返回所有模块可依赖的类型化 AppConfig。
    """
    return ConfigLoader.load(overrides=overrides)


# ============================================================================
# 模型配置查询（向后兼容）
# ============================================================================


def get_model_config(model_name: str) -> dict[str, Any]:
    """解析单个模型配置为字典（兼容旧代码）。

    新代码应通过 AppConfig.models[model_name] 获取 ModelConfig 对象。
    """
    models = _load_models_config()
    if model_name not in models:
        raise KeyError(f"Model '{model_name}' not found in models.yaml")
    mc = models[model_name]
    return {
        "name": mc.name,
        "provider": mc.provider,
        "api_key": mc.api_key,
        "base_url": mc.base_url,
        "temperature": mc.temperature,
        "max_tokens": mc.max_tokens,
    }


def get_default_model() -> str:
    """返回 models.yaml 中的默认模型名。"""
    raw = _load_yaml_with_merge(_MODELS_YAML, "models.yaml")
    return str(raw.get("default_model", "deepseek-v4-pro"))


def get_auxiliary_model() -> str:
    """返回辅助模型名，未配置时回退为 default_model。"""
    raw = _load_yaml_with_merge(_MODELS_YAML, "models.yaml")
    aux = raw.get("auxiliary_model")
    return str(aux) if aux else str(raw.get("default_model", "deepseek-v4-pro"))


def load_models_config() -> Any:
    """返回 models.yaml 中所有模型定义的原始配置（兼容旧代码）。"""
    raw = _load_yaml_with_merge(_MODELS_YAML, "models.yaml")
    return raw.get("models", {})
