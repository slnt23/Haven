import os
from pathlib import Path
from typing import Any

from omegaconf import DictConfig, ListConfig, OmegaConf

from haven.config.settings import _find_user_config

_config: DictConfig | None = None


def _load_config() -> DictConfig | None:
    global _config
    if _config is None:
        _config = OmegaConf.load(Path(__file__).parent / "models.yaml")
        user_config_path = _find_user_config("models.yaml")
        if user_config_path is not None:
            _config = OmegaConf.merge(_config, OmegaConf.load(user_config_path))
        OmegaConf.resolve(_config)
    return _config


def get_default_model() -> str:
    return str(_load_config().default_model)


def load_models_config() -> DictConfig | ListConfig:
    return _load_config().models


def get_model_config(model_name: str) -> dict[str, Any]:
    """将模型名解析为完整配置。

    API Key 从环境变量读取。*models.yaml* 中的 ``api_key_env`` 字段
    指定对应的环境变量名（如 ``DEEPSEEK_API_KEY``）。
    用户只需设置环境变量即可，新增模型无需修改代码。
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
