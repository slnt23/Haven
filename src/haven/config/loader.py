"""模型配置加载器。

从 ``models.yaml`` 读取模型定义，解析 provider / base_url / api_key_env 等字段。
支持内置 ``models.yaml`` 与 CWD 用户 ``models.yaml`` 的 deep-merge 覆盖。
"""

import os
from pathlib import Path
from typing import Any

from omegaconf import DictConfig, ListConfig, OmegaConf

from haven.config.settings import _find_user_config

_config: DictConfig | None = None


def _load_config() -> DictConfig | None:
    """加载 models.yaml，优先内置默认，再用 CWD 用户文件覆盖。

    使用模块级缓存，首次调用后后续直接返回已加载配置。
    """
    global _config
    if _config is None:
        _config = OmegaConf.load(Path(__file__).parent / "models.yaml")
        user_config_path = _find_user_config("models.yaml")
        if user_config_path is not None:
            _config = OmegaConf.merge(_config, OmegaConf.load(user_config_path))
        OmegaConf.resolve(_config)
    return _config


def get_default_model() -> str:
    """返回默认模型名称（models.yaml 中的 default_model 字段）。"""
    return str(_load_config().default_model)


def get_auxiliary_model() -> str:
    """返回辅助模型名称，用于记忆提取、摘要等轻量后台任务。

    若 auxiliary_model 未配置则回退到 default_model。
    """
    cfg = _load_config()
    aux = cfg.get("auxiliary_model", None)
    return str(aux) if aux is not None else str(cfg.default_model)


def load_models_config() -> DictConfig | ListConfig:
    """返回 models.yaml 中所有模型定义的原始配置块。"""
    return _load_config().models


def get_model_config(model_name: str) -> dict[str, Any]:
    """将模型名解析为完整配置字典。

    从 ``models.yaml`` 对应条目提取字段，并通过 ``api_key_env``
    从环境变量读取实际的 API Key。

    Args:
        model_name: 模型名（对应 models.yaml 中 models 下的键）。

    Returns:
        包含 name / provider / api_key / base_url / temperature / max_tokens 的字典。
    """
    models = load_models_config()
    model_cfg = models[model_name]

    api_key_env_name = str(model_cfg.api_key_env)
    api_key = os.environ.get(api_key_env_name, "")

    return {
        "name": model_name,
        "provider": str(model_cfg.provider),
        "api_key": api_key,
        "base_url": str(model_cfg.base_url),
        "temperature": float(model_cfg.temperature),
        "max_tokens": int(model_cfg.max_tokens),
    }
